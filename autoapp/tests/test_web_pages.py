"""
How the server hands out the web interface's files.
"""


def test_the_pages_are_checked_for_a_newer_copy_each_time(client):
    for path in ("/ui/index.html", "/ui/js/common.js", "/ui/css/autoapp.css"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache"
