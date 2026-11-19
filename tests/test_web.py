import requests


def test_home_page_served(base_url):
    response = requests.get(base_url + "/", timeout=10)
    assert response.status_code == 200
    assert "text/html" in response.headers["Content-Type"]
    assert "校园快递代取" in response.text
    assert "/app.js" in response.text


def test_static_css_and_js(base_url):
    css = requests.get(base_url + "/style.css", timeout=10)
    js = requests.get(base_url + "/app.js", timeout=10)
    assert css.status_code == 200
    assert "text/css" in css.headers["Content-Type"]
    assert js.status_code == 200
    assert "application/javascript" in js.headers["Content-Type"]
    assert "async function api" in js.text


def test_favicon_returns_no_content(base_url):
    response = requests.get(base_url + "/favicon.ico", timeout=10)
    assert response.status_code == 204
