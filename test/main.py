import os
from flask import Flask, redirect, url_for, session, request
from oauthlib.oauth2 import WebApplicationClient
import requests
from dotenv import load_dotenv
import logging

# Load environment variables from .env file
load_dotenv()

app = Flask(__name__)
app.secret_key = bytes.fromhex(os.environ['SECRET_KEY'])

GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
GOOGLE_REDIRECT_URI = os.getenv('GOOGLE_REDIRECT_URI')
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
PORT = int(os.getenv('PORT', 5000))
FLASK_ENV = os.getenv('FLASK_ENV', 'production')

# Log environment variables for debugging
logging.basicConfig(level=logging.DEBUG)
app.logger.debug(f"GOOGLE_CLIENT_ID: {GOOGLE_CLIENT_ID}")
app.logger.debug(f"GOOGLE_CLIENT_SECRET: {GOOGLE_CLIENT_SECRET}")
app.logger.debug(f"GOOGLE_REDIRECT_URI: {GOOGLE_REDIRECT_URI}")

client = WebApplicationClient(GOOGLE_CLIENT_ID)

def get_google_provider_cfg():
    return requests.get(GOOGLE_DISCOVERY_URL).json()

@app.before_request
def before_request():
    if 'email' not in session and request.endpoint not in ['login', 'callback']:
        return redirect(url_for('login'))

@app.route("/")
def index():
    return f'Hello, {session["email"]}!'

@app.route("/login")
def login():
    google_provider_cfg = get_google_provider_cfg()
    authorization_endpoint = google_provider_cfg["authorization_endpoint"]

    request_uri = client.prepare_request_uri(
        authorization_endpoint,
        redirect_uri=GOOGLE_REDIRECT_URI,
        scope=["openid", "email", "profile"],
    )
    return redirect(request_uri)

@app.route("/login/callback")
def callback():
    code = request.args.get("code")

    google_provider_cfg = get_google_provider_cfg()
    token_endpoint = google_provider_cfg["token_endpoint"]

    token_url, headers, body = client.prepare_token_request(
        token_endpoint,
        authorization_response=request.url,
        redirect_url=GOOGLE_REDIRECT_URI,
        code=code
    )
    token_response = requests.post(
        token_url,
        headers=headers,
        data=body,
        auth=(GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET),
    )

    client.parse_request_body_response(token_response.text)

    userinfo_endpoint = google_provider_cfg["userinfo_endpoint"]
    uri, headers, body = client.add_token(userinfo_endpoint)
    userinfo_response = requests.get(uri, headers=headers, data=body)

    userinfo = userinfo_response.json()
    session['email'] = userinfo['email']

    return redirect(url_for("index"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

if __name__ == "__main__":
    match FLASK_ENV.lower():
        case 'development':
            app.run(host='localhost', port=PORT, debug=True, ssl_context='adhoc')
        case 'production':
            app.run(host='0.0.0.0', port=PORT, debug=False)
        case _:
            raise ValueError(f"Invalid FLASK_ENV value: {FLASK_ENV}")


