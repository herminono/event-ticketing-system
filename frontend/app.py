
from flask import Flask, render_template, request, jsonify, Response
import requests

app = Flask(__name__)

AUTH_URL = "https://event-ticketing-system-pearl.vercel.app"
TICKETING_URL = "https://event-ticketing-system-qi1m.vercel.app"


@app.get("/")
def home():
    return render_template("index.html")

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    message = None

    if request.method == "POST":
        try:
            response = requests.post(
                f"{AUTH_URL}/auth/forgot-password",
                json={"email": request.form.get("email")},
                timeout=10
            )

            data = response.json()
            message = data.get("message") or data.get("error")

        except (requests.RequestException, ValueError):
            message = "Authentication Service is unavailable."

    return render_template(
        "reset_password.html",
        message=message
    )
@app.route("/reset-password", methods=["GET", "POST"])
def reset_password():
    token = request.values.get("token")
    message = None
    valid = False

    if not token:
        return render_template(
            "reset_password.html",
            message="Please request a password reset link."
        )

    try:
        response = requests.get(
            f"{AUTH_URL}/auth/reset-password",
            params={"token": token},
            timeout=10
        )

        valid = response.status_code == 200

        if request.method == "POST" and valid:
            password = request.form.get("new_password")
            confirmation = request.form.get("confirm_password")

            if password != confirmation:
                message = "Passwords do not match."

            else:
                response = requests.post(
                    f"{AUTH_URL}/auth/reset-password",
                    json={
                        "token": token,
                        "new_password": password
                    },
                    timeout=10
                )

                data = response.json()
                message = data.get("message") or data.get("error")

                if response.status_code == 200:
                    return render_template(
                        "reset_password.html",
                        message=message
                    )

    except (requests.RequestException, ValueError):
        message = "Authentication Service is unavailable."

    return render_template(
        "reset_password.html",
        token=token,
        valid=valid,
        message=message
    )
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
