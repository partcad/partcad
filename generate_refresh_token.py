import json
from google_auth_oauthlib.flow import InstalledAppFlow

# Usage:
# pip install google-auth google-auth-oauthlib
# python generate_refresh_token.py

# Problems:
# - Error 400: redirect_uri_mismatch:
#   """
#   You can't sign in to this app because it doesn't comply with Google's OAuth 2.0 policy.
#   If you're the app developer, register the redirect URI in the Google Cloud Console.
#   Request details: redirect_uri=http://localhost:8080/ flowName=GeneralOAuthFlow
#   """


# Path to your client secrets JSON file
CLIENT_SECRETS_FILE = "client_secrets.json"

# Required scopes for YouTube upload
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def generate_refresh_token() -> None:
    # Initialize the OAuth flow
    flow = InstalledAppFlow.from_client_secrets_file(CLIENT_SECRETS_FILE, SCOPES)

    # Run the local server to authorize
    credentials = flow.run_local_server(port=8080, prompt="consent", authorization_prompt_message="")

    # Check if the credentials have a refresh token
    if not credentials or not credentials.refresh_token:
        print("Failed to obtain refresh token.")
        return

    # Output the refresh token
    print("\nSuccessfully generated a refresh token:")
    print(f"Refresh Token: {credentials.refresh_token}")

    # Optionally save the credentials for later use
    credentials_data = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": credentials.scopes,
    }

    with open("youtube_credentials.json", "w") as creds_file:
        json.dump(credentials_data, creds_file)

    print("\nCredentials saved to 'youtube_credentials.json'.")


if __name__ == "__main__":
    generate_refresh_token()
