import os
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route
from mcp.server.fastmcp import FastMCP
import uvicorn

# --- 1. INITIAL SETUP & CONFIGURATION (No changes here) ---

load_dotenv()
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI")
SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing playlist-read-private playlist-modify-public playlist-modify-private"
sp_oauth = SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope=SCOPES,
    cache_path=".spotipy_cache"
)
sp = None

# --- 2. MCP SERVER AND TOOLS DEFINITION (No changes here) ---

mcp = FastMCP(
    "Spotify Controller",
    description="An MCP server to control Spotify playback and playlists."
)

def check_auth():
    if not sp:
        raise Exception("Not authenticated with Spotify. Please visit /login in your browser to authenticate.")

@mcp.tool()
def search_and_play(query: str) -> str:
    """Searches for a song and plays the first result."""
    check_auth()
    try:
        results = sp.search(q=query, type='track', limit=1)
        if not results['tracks']['items']:
            return f"No results found for '{query}'."
        track = results['tracks']['items'][0]
        track_uri = track['uri']
        sp.start_playback(uris=[track_uri])
        return f"Now playing: {track['name']} by {track['artists'][0]['name']}"
    except Exception as e:
        return f"An error occurred: {e}"

@mcp.tool()
def pause_playback() -> str:
    """Pauses the current playback."""
    check_auth()
    try:
        sp.pause_playback()
        return "Playback paused."
    except Exception as e:
        return f"An error occurred: {e}"

@mcp.tool()
def resume_playback() -> str:
    """Resumes the current playback."""
    check_auth()
    try:
        sp.start_playback()
        return "Playback resumed."
    except Exception as e:
        return f"An error occurred: {e}"

@mcp.tool()
def next_track() -> str:
    """Skips to the next track."""
    check_auth()
    try:
        sp.next_track()
        return "Skipped to the next track."
    except Exception as e:
        return f"An error occurred: {e}"

@mcp.tool()
def get_current_song() -> str:
    """Gets the currently playing song and artist."""
    check_auth()
    try:
        track_info = sp.current_playback()
        if track_info and track_info['is_playing']:
            item = track_info['item']
            return f"Currently playing: {item['name']} by {item['artists'][0]['name']}"
        else:
            return "Nothing is currently playing."
    except Exception as e:
        return f"An error occurred: {e}"

# --- 3. WEB SERVER & AUTHENTICATION (Updated Code) ---

def initialize_spotipy(access_token):
    """Initializes the global spotipy client with the given token."""
    global sp
    sp = spotipy.Spotify(auth=access_token)

async def homepage(request):
    """Homepage that checks for a token and tries to initialize Spotipy."""
    global sp
    try:
        token_info = sp_oauth.get_cached_token()
        if token_info:
            initialize_spotipy(token_info['access_token'])
            return Response("Authenticated with Spotify! You can now use the MCP tools.", media_type="text/plain")
    except Exception:
        pass # Ignore if no token
    return RedirectResponse(url='/login')

async def login(request):
    """Redirects the user to Spotify's authorization page."""
    auth_url = sp_oauth.get_authorize_url()
    return RedirectResponse(url=auth_url)

async def callback(request):
    """Handles the redirect from Spotify after the user grants permission."""
    code = request.query_params['code']
    token_info = sp_oauth.get_access_token(code)
    initialize_spotipy(token_info['access_token'])
    return Response("Successfully authenticated! You can close this tab.", media_type="text/plain")

# ** CORRECTED LINE: Get the pre-configured app from FastMCP **
# This app already includes the necessary /sse endpoint.
app = mcp.sse_app()

# ** NEW: Add our custom authentication routes to the app **
app.add_route("/", homepage)
app.add_route("/login", login)
app.add_route("/callback", callback)

# This part allows us to run the server locally for testing
if __name__ == "__main__":
    print("Starting server. Please open http://localhost:8888 in your browser to authenticate with Spotify.")
    uvicorn.run(app, host="0.0.0.0", port=8888)
