from fastapi.testclient import TestClient

from atelier_api.main import app
from customers.schemas import CustomerRead

testdata_customers : list[CustomerRead] = [ 
    CustomerRead(
        id= 1,
        first_name= "Charles",
        last_name= "Heller",
        email= "charles.heller@hotmail.de",
        phone= "+49123456789"
    ),
    CustomerRead(
        id=2,
        first_name= "David",
        last_name= "Amoako",
        email= "example@hotmail.de",
        phone= "+49123456789"
    )
]

client = TestClient(app)

def test_get_customers():
    response = client.get("/customers")
    assert response.status_code == 200
    expected = [
    customer.model_dump(mode="json")
    for customer in testdata_customers
    ]
    assert response.json() == expected 


