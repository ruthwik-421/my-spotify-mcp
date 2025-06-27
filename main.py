import os
import uuid
import random
import re
import json
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from dotenv import load_dotenv
from starlette.responses import RedirectResponse, Response
from starlette.routing import Route
from mcp.server.fastmcp import FastMCP
import uvicorn
# --- NEW IMPORTS FOR DATABASE ---
from sqlalchemy import create_engine, Column, String, JSON
from sqlalchemy.orm import sessionmaker, declarative_base

# --- 1. CONFIGURATION ---
load_dotenv()
CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET")
REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI")
SCOPES = (
    "user-read-private user-read-playback-state user-modify-playback-state "
    "user-read-currently-playing playlist-read-private playlist-read-collaborative "
    "playlist-modify-public playlist-modify-private user-read-recently-played"
)

# --- NEW: DATABASE SETUP ---
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("No DATABASE_URL found in environment variables. Please set it.")

# SQLAlchemy setup
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# SQLAlchemy model for our sessions table
class SpotifySession(Base):
    __tablename__ = "spotify_sessions"
    session_id = Column(String, primary_key=True, index=True)
    token_info = Column(JSON)

# Create the table if it doesn't exist
Base.metadata.create_all(bind=engine)

# --- 2. AUTHENTICATION & SESSION HELPERS ---

def create_spotify_oauth():
    """Creates a SpotifyOAuth instance for the authentication flow."""
    return SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPES,
    )

def get_sp_for_session(session_id: str):
    """
    Given a session_id, retrieve the token from the database, create an authenticated
    Spotipy client, and return it.
    """
    db = SessionLocal()
    try:
        db_session = db.query(SpotifySession).filter(SpotifySession.session_id == session_id).first()
        if not db_session:
            raise Exception("Invalid or expired session_id. Please log in again via the web interface to get a new one.")

        token_info = db_session.token_info

        # Refresh token if expired and update the database
        if SpotifyOAuth.is_token_expired(token_info):
            sp_oauth = create_spotify_oauth()
            token_info = sp_oauth.refresh_access_token(token_info["refresh_token"])
            db_session.token_info = token_info
            db.commit()

        return spotipy.Spotify(auth=token_info["access_token"])
    finally:
        db.close()

# --- 3. MCP SERVER AND TOOLS DEFINITION ---
mcp = FastMCP(
    "Public Spotify Controller",
    description="A multi-user MCP server to control Spotify playback, playlists, and history."
)

@mcp.tool()
def search_and_play(session_id: str, query: str) -> str:
    """Searches for a song and plays the first result for the given session."""
    sp = get_sp_for_session(session_id)
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
def pause_playback(session_id: str) -> str:
    """Pauses the current playback for the given session."""
    sp = get_sp_for_session(session_id)
    try:
        sp.pause_playback()
        return "Playback paused."
    except Exception as e:
        return f"An error occurred: {e}"

@mcp.tool()
def resume_playback(session_id: str) -> str:
    """Resumes the current playback for the given session."""
    sp = get_sp_for_session(session_id)
    try:
        sp.start_playback()
        return "Playback resumed."
    except Exception as e:
        return f"An error occurred: {e}"

@mcp.tool()
def next_track(session_id: str) -> str:
    """Skips to the next track for the given session."""
    sp = get_sp_for_session(session_id)
    try:
        sp.next_track()
        return "Skipped to the next track."
    except Exception as e:
        return f"An error occurred: {e}"

@mcp.tool()
def get_current_song(session_id: str) -> str:
    """Gets the currently playing song and artist for the given session."""
    sp = get_sp_for_session(session_id)
    try:
        track_info = sp.current_playback()
        if track_info and track_info['is_playing']:
            item = track_info['item']
            return f"Currently playing: {item['name']} by {item['artists'][0]['name']}"
        else:
            return "Nothing is currently playing."
    except Exception as e:
        return f"An error occurred: {e}"

@mcp.tool()
def get_my_playlists(session_id: str) -> str:
    """Retrieves all playlists for the user of the given session."""
    sp = get_sp_for_session(session_id)
    try:
        playlists = sp.current_user_playlists()
        if not playlists['items']:
            return "You don't have any playlists."
        playlist_names = [p['name'] for p in playlists['items']]
        return "Here are your playlists:\n" + "\n".join(f"- {name}" for name in playlist_names)
    except Exception as e:
        return f"An error occurred: {e}"

@mcp.tool()
def get_recently_played(session_id: str) -> str:
    """Gets the last 5 recently played tracks for the user of the given session."""
    sp = get_sp_for_session(session_id)
    try:
        results = sp.current_user_recently_played(limit=5)
        if not results['items']:
            return "You haven't played any tracks recently."
        tracks = [f"{item['track']['name']} by {item['track']['artists'][0]['name']}" for item in results['items']]
        return "Here are your recently played tracks:\n" + "\n".join(f"- {track}" for track in tracks)
    except Exception as e:
        return f"An error occurred: {e}"
        
@mcp.tool()
def add_to_playlist(session_id: str, song_query: str, playlist_name: str) -> str:
    """Searches for a song and adds it to one of the user's playlists."""
    sp = get_sp_for_session(session_id)
    try:
        results = sp.search(q=song_query, type='track', limit=1)
        if not results['tracks']['items']:
            return f"Could not find the song: '{song_query}'."
        track = results['tracks']['items'][0]
        playlists = sp.current_user_playlists()
        target_playlist = None
        for p in playlists['items']:
            if p['name'].lower() == playlist_name.lower():
                target_playlist = p
                break
        if not target_playlist:
            return f"Could not find a playlist named '{playlist_name}'."
        sp.playlist_add_items(target_playlist['id'], [track['uri']])
        return f"Successfully added '{track['name']}' to your '{playlist_name}' playlist."
    except Exception as e:
        return f"An error occurred: {e}"

# --- 4. WEB SERVER (STARLETTE) ---

async def login(request):
    """Redirects the user to Spotify's authorization page."""
    sp_oauth = create_spotify_oauth()
    auth_url = sp_oauth.get_authorize_url()
    return RedirectResponse(url=auth_url)

async def callback(request):
    """
    Handles the redirect, generates a session_id, and stores the token in the database.
    """
    sp_oauth = create_spotify_oauth()
    code = request.query_params['code']
    token_info = sp_oauth.get_access_token(code, as_dict=True)

    temp_sp = spotipy.Spotify(auth=token_info["access_token"])
    user_profile = temp_sp.current_user()
    
    display_name = user_profile.get('display_name', 'user')
    sanitized_name = re.sub(r'[^a-zA-Z0-9]', '-', display_name).lower()
    random_id = random.randint(100, 999)
    session_id = f"{sanitized_name}-{random_id}"

    # --- NEW: Save session to database ---
    db = SessionLocal()
    try:
        # Check if a session for this user already exists, update it, otherwise create new
        existing_session = db.query(SpotifySession).filter(SpotifySession.token_info['refresh_token'] == token_info['refresh_token']).first()
        if existing_session:
            existing_session.token_info = token_info
            session_id = existing_session.session_id # Reuse the existing session_id
        else:
            new_session = SpotifySession(session_id=session_id, token_info=token_info)
            db.add(new_session)
        db.commit()
    finally:
        db.close()

    html_content = f"""
    <html>
        <head><title>Authentication Successful</title>
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #121212; color: #ffffff; display: flex; justify-content: center; align-items: center; height: 100vh; margin: 0; }}
                .container {{ background-color: #282828; padding: 40px; border-radius: 10px; text-align: center; box-shadow: 0 4px 20px rgba(0,0,0,0.5); max-width: 90%; }}
                h1 {{ color: #1DB954; }} p {{ font-size: 1.1em; line-height: 1.6;}}
                code {{ background-color: #535353; padding: 15px; border-radius: 5px; font-family: monospace; user-select: all; word-break: break-all; display: inline-block; margin-top: 10px; font-size: 1.2em; }}
            </style>
        </head>
        <body>
            <div class="container">
                <h1>Authentication Successful!</h1>
                <p>Your session is now saved permanently. Copy your Session ID below and provide it to your AI assistant. You can now close this tab.</p>
                <p><code>{session_id}</code></p>
            </div>
        </body>
    </html>
    """
    return Response(html_content, media_type="text/html")

app = mcp.sse_app()
app.add_route("/login", login)
app.add_route("/", lambda req: RedirectResponse(url='/login'), methods=['GET'])
app.add_route("/callback", callback)

if __name__ == "__main__":
    print("Starting server. Please open http://localhost:8888/login in your browser to authenticate with Spotify.")
    uvicorn.run(app, host="0.0.0.0", port=8888)
