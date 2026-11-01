#!/usr/bin/env bash
# Temporary process-boundary probe: preserve command failures and the CI deadline.
set -uo pipefail
export PYTHONUNBUFFERED=1 PYTHONFAULTHANDLER=1
export PYTEST='python -u -m scripts.pytest_diagnostics'
interval=${PYTEST_DIAGNOSTIC_INTERVAL:-30}
probe_dir=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/atelier-pytest.XXXXXX")
export PYTEST_DIAGNOSTIC_PIDFILE="$probe_dir/python.pid"
watchdog_pid=''

mark() {
  printf 'SHELL_DIAGNOSTIC at=%s phase=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"
}

cleanup() {
  if [[ -n "$watchdog_pid" ]]; then
    kill "$watchdog_pid" 2>/dev/null || true
    wait "$watchdog_pid" 2>/dev/null || true
  fi
  rm -rf "$probe_dir"
}
trap cleanup EXIT

mark "shell_step_start pid=$$"
# A dedicated group keeps orphaned descendants visible after their parent exits.
python3 -c 'import os, signal, sys; os.setsid(); signal.signal(signal.SIGINT, signal.SIG_DFL); signal.signal(signal.SIGTERM, signal.SIG_DFL); os.execvp(sys.argv[1], sys.argv[1:])' "$@" &
command_pid=$!
printf '%s\n' "$command_pid" > "$probe_dir/command.pid"
signal_exit=0
trap 'signal_exit=130; mark signal_INT; kill -INT -- "-$command_pid" 2>/dev/null || kill -TERM "$command_pid" 2>/dev/null || true' INT
trap 'signal_exit=143; mark signal_TERM; kill -TERM -- "-$command_pid" 2>/dev/null || kill -TERM "$command_pid" 2>/dev/null || true' TERM

watchdog() {
  local stopping=0 active_child='' child_status=0 stat_line='' stat_tail=''
  local -a stat_fields

  stop_watchdog() {
    stopping=1
    # Only stateless diagnostic helpers are killed, never the monitored command.
    if [[ -n "$active_child" ]]; then
      kill -KILL "$active_child" 2>/dev/null || true
    fi
  }

  run_owned() {
    # wait is interruptible by traps; a foreground pipeline is not. Every helper
    # is a direct child, with no untracked pipeline/sleep inheriting the CI pipe.
    "$@" &
    active_child=$!
    if [[ "$stopping" == 1 ]]; then
      kill -KILL "$active_child" 2>/dev/null || true
    fi
    wait "$active_child" 2>/dev/null
    child_status=$?
    if [[ "$stopping" == 1 ]]; then
      kill -KILL "$active_child" 2>/dev/null || true
      wait "$active_child" 2>/dev/null || true
    fi
    active_child=''
    return "$child_status"
  }

  trap stop_watchdog TERM INT
  while [[ "$stopping" == 0 ]] && kill -0 "$command_pid" 2>/dev/null; do
    mark "watchdog command_pid=$command_pid"
    # Names only: command arguments, SQL and environment values are excluded.
    run_owned ps -eo pid,ppid,pgid,stat,etime,comm > "$probe_dir/processes" 2>/dev/null
    [[ "$stopping" == 0 ]] || break
    run_owned awk -v root="$$" -v group="$command_pid" '
      NR > 1 { parent[$1]=$2; pg[$1]=$3; row[$1]=$0 }
      END { for (pid in row) { p=pid; for (i=0; p>0 && i<100; i++) {
        if (p==root || (pid in row && pg[pid]==group)) { print "PROCESS_DIAGNOSTIC " row[pid]; break }
        p=parent[p]
      } } }' "$probe_dir/processes"
    [[ "$stopping" == 0 ]] || break
    if [[ -r "$PYTEST_DIAGNOSTIC_PIDFILE" ]]; then
      read -r python_pid start_token < "$PYTEST_DIAGNOSTIC_PIDFILE"
      if [[ "$python_pid" =~ ^[0-9]+$ ]] && kill -0 "$python_pid" 2>/dev/null; then
        current_token='-'
        if [[ -r "/proc/$python_pid/stat" ]]; then
          read -r stat_line < "/proc/$python_pid/stat" || stat_line=''
          stat_tail=${stat_line##*) }
          read -ra stat_fields <<< "$stat_tail"
          current_token=${stat_fields[19]:-unknown}
        fi
        if [[ "$start_token" == "$current_token" && "$stopping" == 0 ]]; then
          kill -USR1 "$python_pid" 2>/dev/null || true
        fi
      else
        mark "python_process_not_alive pid=$python_pid"
      fi
    fi
    [[ "$stopping" == 0 ]] || break
    run_owned sleep "$interval" >/dev/null 2>&1
  done
}

watchdog &
watchdog_pid=$!
# A trapped signal interrupts wait before the child necessarily exits. Re-wait
# until the owned process has been reaped rather than orphaning its session.
while :; do
  wait "$command_pid"
  code=$?
  kill -0 "$command_pid" 2>/dev/null || break
done
if [[ "$signal_exit" != 0 ]]; then
  code=$signal_exit
fi
mark "command_process_exit code=$code"
if [[ -r "$PYTEST_DIAGNOSTIC_PIDFILE" ]]; then
  read -r python_pid _ < "$PYTEST_DIAGNOSTIC_PIDFILE"
  if kill -0 "$python_pid" 2>/dev/null; then
    mark "python_process_still_present pid=$python_pid"
    [[ "$code" != 0 ]] || code=1
  else
    mark "python_process_exit_observed pid=$python_pid"
  fi
fi
remaining=$(ps -eo pid,ppid,pgid,stat,etime,comm | awk -v group="$command_pid" 'NR>1 && $3==group && $4 !~ /^Z/ {print}')
scan_status=$?
if [[ "$scan_status" != 0 ]]; then
  mark "remaining_process_scan_failed"
  [[ "$code" != 0 ]] || code=1
fi
if [[ -n "$remaining" ]]; then
  mark "remaining_descendants_after_command_exit"
  printf '%s\n' "$remaining"
  [[ "$code" != 0 ]] || code=1
fi
# The owned session has ended; do not leak descendants even if inspection failed.
kill -KILL -- "-$command_pid" 2>/dev/null || true
cleanup
watchdog_pid=''
mark "shell_step_complete code=$code"
exit "$code"
