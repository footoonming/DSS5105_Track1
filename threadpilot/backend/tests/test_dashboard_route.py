"""The morning-briefing dashboard (demo/briefing_demo.html) is served by the backend at /dashboard."""
from .test_api import client  # noqa: F401  (pytest fixture)


def test_dashboard_address_opens_the_page(client):
    for path in ('/dashboard', '/dashboard/'):
        r = client.get(path, follow_redirects=False)
        assert r.status_code == 307 and r.headers['location'] == '/dashboard/briefing_demo.html', path
    page = client.get('/dashboard/briefing_demo.html')
    assert page.status_code == 200 and 'ThreadPilot' in page.text and 'id="liveLink"' in page.text


def test_dashboard_serves_nothing_else(client):
    for url in ('/dashboard/../backend/.env', '/dashboard/../data/orders.csv', '/dashboard/simulate.py', '/dashboard/missing.html'):
        assert client.get(url).status_code == 404, url


def test_dashboard_stays_out_of_the_api_schema(client):
    assert not any(p.startswith('/dashboard') for p in client.get('/openapi.json').json()['paths'])


def test_cover_button_opens_the_dashboard(client):
    app_js = client.get('/app.js').text
    assert 'href="/dashboard">Enter today’s dashboard' in app_js
    assert "location.replace('/dashboard')" not in app_js           # the team's Dashboard tab is not redirected
    assert "['/dashboard','☀','Morning Briefing']" in app_js          # the sidebar has a Morning Briefing tab
    assert "r.startsWith('/')?r:'#/'+r" in app_js                     # ...which links to the page, not to a #/ route
    page = client.get('/dashboard/briefing_demo.html').text
    assert 'id="liveLink" href="/#/dashboard"' in page               # the briefing's Live app button opens the team's app
