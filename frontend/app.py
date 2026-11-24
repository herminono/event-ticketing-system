
from flask import Flask, render_template, request, jsonify, Response
import requests

app = Flask(__name__)

AUTH_URL = "https://event-ticketing-system-pearl.vercel.app/"
TICKETING_URL = "https://event-ticketing-system-qi1m.vercel.app/"


@app.get("/")
def home():
    return render_template("index.html")


def forward_request(base_url, path):
    url = f"{base_url}/{path}"

    headers = {}
    for name in ("Authorization", "Idempotency-Key"):
        value = request.headers.get(name)
        if value:
            headers[name] = value

    try:
        response = requests.request(
            method=request.method,
            url=url,
            params=request.args,
            json=request.get_json(silent=True),
            headers=headers,
            timeout=15
        )

        return Response(
            response.content,
            status=response.status_code,
            content_type=response.headers.get(
                "Content-Type", "application/json"
            )
        )

    except requests.RequestException:
        return jsonify({
            "error": "Backend service unavailable"
        }), 502


@app.route(
    "/api/auth/<path:path>",
    methods=["GET", "POST", "PATCH", "DELETE"]
)
def auth_proxy(path):
    return forward_request(AUTH_URL, path)


@app.route(
    "/api/ticketing/<path:path>",
    methods=["GET", "POST", "PATCH", "DELETE"]
)
def ticketing_proxy(path):
    return forward_request(TICKETING_URL, path)


if __name__ == "__main__":
    app.run(port=8000, debug=False)
