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
python3 -c 'import os, sys; os.setsid(); os.execvp(sys.argv[1], sys.argv[1:])' "$@" &
command_pid=$!
trap 'mark signal_INT; kill -INT -- "-$command_pid" 2>/dev/null || true' INT
trap 'mark signal_TERM; kill -TERM -- "-$command_pid" 2>/dev/null || true' TERM

watchdog() {
  sleeper=''
  trap 'if [[ -n "$sleeper" ]]; then kill "$sleeper" 2>/dev/null || true; wait "$sleeper" 2>/dev/null || true; fi; exit 0' TERM INT
  while kill -0 "$command_pid" 2>/dev/null; do
    mark "watchdog command_pid=$command_pid"
    # Names only: command arguments, SQL and environment values are excluded.
    ps -eo pid,ppid,pgid,stat,etime,comm | awk -v root="$$" -v group="$command_pid" '
      NR > 1 { parent[$1]=$2; pg[$1]=$3; row[$1]=$0 }
      END { for (pid in row) { p=pid; for (i=0; p>0 && i<100; i++) {
        if (p==root || (pid in row && pg[pid]==group)) { print "PROCESS_DIAGNOSTIC " row[pid]; break }
        p=parent[p]
      } } }'
    if [[ -r "$PYTEST_DIAGNOSTIC_PIDFILE" ]]; then
      read -r python_pid start_token < "$PYTEST_DIAGNOSTIC_PIDFILE"
      if [[ "$python_pid" =~ ^[0-9]+$ ]] && kill -0 "$python_pid" 2>/dev/null; then
        current_token='-'
        if [[ -r "/proc/$python_pid/stat" ]]; then
          current_token=$(awk '{print $22}' "/proc/$python_pid/stat")
        fi
        # Avoid signalling a recycled PID after the recorded interpreter exits.
        if [[ "$start_token" == "$current_token" ]]; then
          kill -USR1 "$python_pid" 2>/dev/null || true
        fi
      else
        mark "python_process_not_alive pid=$python_pid"
      fi
    fi
    sleep "$interval" &
    sleeper=$!
    wait "$sleeper" || true
  done
}
watchdog &
watchdog_pid=$!
wait "$command_pid"
code=$?
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
if [[ -n "$remaining" ]]; then
  mark "remaining_descendants_after_command_exit"
  printf '%s\n' "$remaining"
  [[ "$code" != 0 ]] || code=1
fi
cleanup
watchdog_pid=''
mark "shell_step_complete code=$code"
exit "$code"
