import streamlit as st
import requests
import pandas as pd
import plotly.express as px
import random
from datetime import datetime
import os
from urllib.parse import urlparse
import psycopg2

# ====================== CONFIG ======================
st.set_page_config(page_title="European Sports Analytics", layout="wide")

# API Keys from Railway Variables
FD_API_KEY = os.getenv("FD_API_KEY")
ODDS_API_KEY = os.getenv("ODDS_API_KEY")

FD_BASE_URL = "https://api.football-data.org/v4"
ODDS_BASE_URL = "https://api.the-odds-api.com/v4/sports"   # Correct URL

fd_headers = {"X-Auth-Token": FD_API_KEY} if FD_API_KEY else {}

# League mapping: football-data.org code → the-odds-api key
LEAGUE_MAP = {
    "PL": "soccer_epl",
    "PD": "soccer_spain_la_liga",
    "SA": "soccer_italy_serie_a",
    "BL": "soccer_germany_bundesliga",
    "FL": "soccer_france_ligue_one",
    # Add more as needed (e.g. "DED": "soccer_netherlands_eredivisie")
}

# ====================== DATABASE (PostgreSQL) ======================
@st.cache_resource
def get_db_connection():
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        st.error("DATABASE_URL environment variable is missing!")
        st.stop()
    result = urlparse(DATABASE_URL)
    return psycopg2.connect(
        dbname=result.path[1:],
        user=result.username,
        password=result.password,
        host=result.hostname,
        port=result.port
    )

conn = get_db_connection()
c = conn.cursor()

# Create tables (Postgres syntax)
c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE,
        balance INTEGER DEFAULT 1000
    )
""")
c.execute("""
    CREATE TABLE IF NOT EXISTS bets (
        id SERIAL PRIMARY KEY,
        username TEXT,
        team TEXT,
        coins INTEGER,
        odds REAL,
        result TEXT,
        balance INTEGER,
        date TEXT
    )
""")
conn.commit()

# ====================== HELPER FUNCTIONS ======================
def get_competitions():
    if not FD_API_KEY:
        return {"competitions": []}
    try:
        response = requests.get(f"{FD_BASE_URL}/competitions", headers=fd_headers, timeout=10)
        response.raise_for_status()
        return response.json()
    except:
        return {"competitions": []}

def get_odds(odds_key):
    if not ODDS_API_KEY or not odds_key:
        return []
    try:
        params = {
            "apiKey": ODDS_API_KEY,
            "regions": "eu",
            "markets": "h2h",
            "oddsFormat": "decimal"
        }
        response = requests.get(f"{ODDS_BASE_URL}/{odds_key}/odds", params=params, timeout=10)
        response.raise_for_status()
        return response.json()
    except:
        return []

def plot_balance(username):
    c.execute("SELECT date, balance FROM bets WHERE username=%s ORDER BY date", (username,))
    df = pd.DataFrame(c.fetchall(), columns=["date", "balance"])
    if df.empty:
        st.info("No bets yet.")
        return
    fig = px.line(df, x="date", y="balance", title=f"{username}'s Balance History")
    st.plotly_chart(fig, use_container_width=True)

def plot_leaderboard():
    c.execute("SELECT username, balance FROM users ORDER BY balance DESC")
    df = pd.DataFrame(c.fetchall(), columns=["username", "balance"])
    st.table(df)

# ====================== STREAMLIT UI ======================
st.title("⚽ European Sports Analytics Dashboard with Live Odds")

# Sidebar Login
st.sidebar.title("👤 User Login")
username = st.sidebar.text_input("Enter username")
if st.sidebar.button("Login / Register"):
    try:
        c.execute("INSERT INTO users (username) VALUES (%s)", (username,))
        conn.commit()
        st.sidebar.success(f"Welcome {username}! Starting balance: 1000 coins")
    except psycopg2.errors.UniqueViolation:
        st.sidebar.info(f"Welcome back, {username}!")
    except Exception as e:
        st.sidebar.error(str(e))

# League selector
competitions_data = get_competitions()
european_leagues = []
for comp in competitions_data.get("competitions", []):
    if comp.get("area", {}).get("name") in [
        "England", "Spain", "Italy", "Germany", "France", "Netherlands", "Portugal",
        "Turkey", "Belgium", "Switzerland", "Austria", "Scotland", "Greece", "Poland",
        "Czech Republic", "Russia", "Ukraine", "Norway", "Sweden", "Denmark", "Finland"
    ] and comp.get("type") == "LEAGUE":
        european_leagues.append({
            "name": comp["name"],
            "code": comp["code"],
            "country": comp["area"]["name"]
        })

df_leagues = pd.DataFrame(european_leagues)
st.subheader("🇪🇺 European Leagues")
st.dataframe(df_leagues, use_container_width=True)

if not df_leagues.empty:
    league_choice = st.selectbox("Select a League", df_leagues["name"])
    league_code = df_leagues[df_leagues["name"] == league_choice]["code"].values[0]
    odds_key = LEAGUE_MAP.get(league_code, "soccer_epl")  # fallback to EPL

    st.write(f"Selected: **{league_choice}** ({league_code}) → Odds key: `{odds_key}`")

    # Live Odds
    st.subheader("📊 Live Odds (≤ 1.50)")
    odds_data = get_odds(odds_key)

    if odds_data:
        for match in odds_data:
            home = match.get("home_team", "N/A")
            away = match.get("away_team", "N/A")
            for bookmaker in match.get("bookmakers", []):
                for market in bookmaker.get("markets", []):
                    if market.get("key") == "h2h":
                        for outcome in market.get("outcomes", []):
                            if outcome.get("price", 999) <= 1.50:
                                st.success(
                                    f"**{outcome['name']}** vs {home if outcome['name'] != home else away} "
                                    f"→ Odds: **{outcome['price']}** ({bookmaker['title']})"
                                )
    else:
        st.info("No odds data (check API key or rate limit)")

# Fantasy Coins Simulator
st.subheader("🎮 Fantasy Coins Simulator")
coins = st.number_input("Coins to bet:", min_value=10, step=10)

if st.button("Place Bet (Simulate)"):
    if username:
        c.execute("SELECT balance FROM users WHERE username=%s", (username,))
        result = c.fetchone()
        balance = result[0] if result else 1000

        result = random.choice(["WIN", "LOSS"])
        odds = 1.50
        if result == "WIN":
            balance += int(coins * odds)
            st.success(f"🎉 WIN! New balance: **{balance}** coins")
        else:
            balance -= coins
            st.error(f"😢 LOSS. New balance: **{balance}** coins")

        c.execute("UPDATE users SET balance=%s WHERE username=%s", (balance, username))
        c.execute(
            "INSERT INTO bets (username, team, coins, odds, result, balance, date) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (username, "Simulated Match", coins, odds, result, balance, datetime.now().strftime("%Y-%m-%d %H:%M"))
        )
        conn.commit()
    else:
        st.warning("Login first!")

# Leaderboard & History
st.subheader("🏆 Leaderboard")
plot_leaderboard()

if username:
    st.subheader("💰 Your Balance Trend")
    plot_balance(username)