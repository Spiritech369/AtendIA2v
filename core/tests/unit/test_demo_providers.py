import pytest
from uuid import uuid4


@pytest.mark.asyncio
async def test_demo_advisor_list_returns_all():
    from atendia._demo.providers import DemoAdvisorProvider
    provider = DemoAdvisorProvider()
    result = await provider.list_advisors()
    assert len(result) == 8
    assert all("id" in a and "name" in a for a in result)


@pytest.mark.asyncio
async def test_demo_advisor_get_returns_match():
    from atendia._demo.providers import DemoAdvisorProvider
    provider = DemoAdvisorProvider()
    result = await provider.get_advisor("maria_gonzalez")
    assert result is not None
    assert result["name"] == "María González"


@pytest.mark.asyncio
async def test_demo_advisor_get_unknown_returns_none():
    from atendia._demo.providers import DemoAdvisorProvider
    provider = DemoAdvisorProvider()
    result = await provider.get_advisor("nobody")
    assert result is None


@pytest.mark.asyncio
async def test_demo_vehicle_list_returns_all():
    from atendia._demo.providers import DemoVehicleProvider
    provider = DemoVehicleProvider()
    result = await provider.list_vehicles()
    assert len(result) == 8
    assert all("id" in v and "label" in v for v in result)


@pytest.mark.asyncio
async def test_demo_vehicle_get_returns_match():
    from atendia._demo.providers import DemoVehicleProvider
    provider = DemoVehicleProvider()
    result = await provider.get_vehicle("jetta_2024")
    assert result is not None
    assert result["label"] == "Jetta 2024"


@pytest.mark.asyncio
async def test_demo_vehicle_get_unknown_returns_none():
    from atendia._demo.providers import DemoVehicleProvider
    provider = DemoVehicleProvider()
    result = await provider.get_vehicle("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_demo_messaging_send_reminder_returns_simulated():
    from atendia._demo.providers import DemoMessageActionProvider
    provider = DemoMessageActionProvider()
    result = await provider.send_reminder(uuid4())
    assert result["status"] == "simulated"
    assert result["_demo"] is True


@pytest.mark.asyncio
async def test_demo_messaging_send_location_returns_simulated():
    from atendia._demo.providers import DemoMessageActionProvider
    provider = DemoMessageActionProvider()
    result = await provider.send_location(uuid4())
    assert result["status"] == "simulated"
    assert result["_demo"] is True


@pytest.mark.asyncio
async def test_demo_messaging_request_documents_returns_simulated():
    from atendia._demo.providers import DemoMessageActionProvider
    provider = DemoMessageActionProvider()
    result = await provider.request_documents(uuid4())
    assert result["status"] == "simulated"
    assert result["_demo"] is True
