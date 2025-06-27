import os
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
from starlette.applications import Starlette
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route, Mount
from mcp.server.fastmcp import FastMCP
from mcp.server.sse import SseServerTransport
import uvicorn

# --- 1. INITIAL SETUP & CONFIGURATION ---

# Load environment variables from .env file for local development
load_dotenv()

# Get Spotify credentials from environment variables
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI")

# Define the permissions our app will ask the user for.
# You can find all available scopes in the Spotipy documentation.
SCOPES = "user-read-playback-state user-modify-playback-state user-read-currently-playing playlist-read-private playlist-modify-public playlist-modify-private"

# This object will handle the OAuth flow and store the user's token.
# The cache file stores the token so you don't have to log in every time.
sp_oauth = SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope=SCOPES,
    cache_path=".spotipy_cache"
)

# Global variable to hold the authenticated Spotipy client
sp = None

# --- 2. MCP SERVER AND TOOLS DEFINITION ---

# Initialize our FastMCP server
mcp = FastMCP(
    "Spotify Controller",
    description="An MCP server to control Spotify playback and playlists."
)

# Helper function to check if the user is authenticated
def check_auth():
    """Checks if the Spotipy client is authenticated. Raises an exception if not."""
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

# --- 3. WEB SERVER (STARLETTE) FOR AUTHENTICATION & SERVING MCP ---

# This function initializes the authenticated Spotipy client
def initialize_spotipy(access_token):
    """Initializes the global spotipy client with the given token."""
    global sp
    sp = spotipy.Spotify(auth=access_token)

# This is the main web app that will handle HTTP requests
# It has three routes: /, /login, and /callback

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
    # The token is now cached in .spotipy_cache
    initialize_spotipy(token_info['access_token'])
    return Response("Successfully authenticated! You can close this tab.", media_type="text/plain")

# --- 4. COMBINING MCP AND WEB SERVER ---

# Setup the SSE transport for the MCP server. This is what AI clients will connect to.
sse = SseServerTransport("/messages/")

async def handle_sse(request):
    """This function handles the connection from an MCP client."""
    async with sse.connect_sse(request.scope, request.receive, request._send) as (
        read_stream,
        write_stream,
    ):
        # ** FIX: The call to mcp.run() is simplified here **
        await mcp.run(read_stream, write_stream)

# Define all the routes for our application
routes = [
    Route("/", endpoint=homepage),
    Route("/login", endpoint=login),
    Route("/callback", endpoint=callback),
    Route("/sse", endpoint=handle_sse),
    Mount("/messages/", app=sse.handle_post_message),
]

# Create the main Starlette application
app = Starlette(debug=True, routes=routes)


# This part allows us to run the server locally for testing
if __name__ == "__main__":
    print("Starting server. Please open http://localhost:8888 in your browser to authenticate with Spotify.")
    uvicorn.run(app, host="0.0.0.0", port=8888)
