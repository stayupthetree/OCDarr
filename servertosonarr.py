import os
import requests
import xml.etree.ElementTree as ET
import logging
import json
from dotenv import load_dotenv

# Load settings from a JSON configuration file
def load_config():
    config_path = os.getenv('CONFIG_PATH', '/app/config/config.json')  # Ensure this path is correct
    with open(config_path, 'r') as file:
        config = json.load(file)
    print("Loaded configuration:", config)  # Debug output
    return config

config = load_config()
# Load environment variables
load_dotenv()

# Define global variables based on environment settings

SONARR_URL = os.getenv('SONARR_URL')
SONARR_API_KEY = os.getenv('SONARR_API_KEY')
LOG_PATH = os.getenv('LOG_PATH', '/app/logs/app.log')


# Set operation-specific settings from config file
get_option = config['get_option']
action_option = config['action_option']
keep_watched = config['keep_watched']
always_keep = config['always_keep']
monitor_watched = config['monitor_watched']

# Setup logging
logging.basicConfig(filename=LOG_PATH, level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')


def get_server_activity():
    """Read current viewing details from Tautulli webhook stored data, using the updated labels."""
    try:
        with open('/app/temp/data_from_tautulli.json', 'r') as file:
            data = json.load(file)
        series_title = data['plex_title']  # Updated to use plex_title
        season_number = int(data['plex_season_num'])  # Updated to use plex_season_num
        episode_number = int(data['plex_ep_num'])  # Updated to use plex_ep_num
        return series_title, season_number, episode_number
    except Exception as e:
        logging.error(f"Failed to read or parse data from Tautulli webhook: {str(e)}")
    return None, None, None



def get_series_id(series_name):
    """Fetch series ID by name from Sonarr."""
    url = f"{SONARR_URL}/api/v3/series"
    headers = {'X-Api-Key': SONARR_API_KEY}
    response = requests.get(url, headers=headers)
    if response.ok:
        series_list = response.json()
        for series in series_list:
            if series['title'].lower() == series_name.lower():
                return series['id']
    else:
        logging.error("Failed to fetch series ID.")
    return None

def get_episode_details(series_id, season_number):
    """Fetch details of episodes for a specific series and season from Sonarr."""
    url = f"{SONARR_URL}/api/v3/episode?seriesId={series_id}&seasonNumber={season_number}"
    headers = {'X-Api-Key': SONARR_API_KEY}
    response = requests.get(url, headers=headers)
    if response.ok:
        episode_details = response.json()
        # Add series title to each episode
        series_title = get_series_title(series_id)
        for episode in episode_details:
            episode['seriesTitle'] = series_title
        return episode_details
    logging.error("Failed to fetch episode details.")
    return []

def get_series_title(series_id):
    """Fetch series title by series ID from Sonarr."""
    url = f"{SONARR_URL}/api/v3/series/{series_id}"
    headers = {'X-Api-Key': SONARR_API_KEY}
    response = requests.get(url, headers=headers)
    if response.ok:
        return response.json()['title']
    logging.error("Failed to fetch series title.")
    return None

def monitor_episodes(episode_ids, monitor=True):
    """Set episodes to monitored or unmonitored in Sonarr."""
    url = f"{SONARR_URL}/api/v3/episode/monitor"
    headers = {'X-Api-Key': SONARR_API_KEY, 'Content-Type': 'application/json'}
    data = {"episodeIds": episode_ids, "monitored": monitor}
    response = requests.put(url, json=data, headers=headers)
    if response.ok:
        logging.info(f"Episodes {episode_ids} set to monitored: {monitor}")
    else:
        logging.error(f"Failed to set episodes to monitored. Response: {response.text}")

def trigger_episode_search_in_sonarr(episode_ids):
    """Trigger a search for specified episodes in Sonarr."""
    url = f"{SONARR_URL}/api/v3/command"
    headers = {'X-Api-Key': SONARR_API_KEY, 'Content-Type': 'application/json'}
    data = {"name": "EpisodeSearch", "episodeIds": episode_ids}
    response = requests.post(url, json=data, headers=headers)
    if response.ok:
        logging.info("Episode search command sent to Sonarr successfully.")
    else:
        logging.error("Failed to send episode search command. Response:", response.text)



def unmonitor_episodes(episode_ids):
    """Unmonitor specified episodes in Sonarr."""
    unmonitor_url = f"{SONARR_URL}/api/v3/episode/monitor"
    unmonitor_data = {"episodeIds": episode_ids, "monitored": False}
    unmonitor_headers = {'X-Api-Key': SONARR_API_KEY, 'Content-Type': 'application/json'}
    response = requests.put(unmonitor_url, json=unmonitor_data, headers=unmonitor_headers)
    if response.ok:
        logging.info(f"Episodes {episode_ids} unmonitored successfully.")
    else:
        logging.error(f"Failed to unmonitor episodes. Response: {response.text}")

def find_episodes_to_delete(episode_details, current_episode_number):
    """Find episodes before the current episode to potentially delete, checking against 'ALWAYS_KEEP'."""
    episodes_to_delete = []
    for ep in episode_details:
        if ep['episodeNumber'] < current_episode_number and ep['seriesTitle'] not in ALWAYS_KEEP:
            if ep['episodeFileId'] > 0:  # Ensure there is a file to delete
                episodes_to_delete.append(ep['episodeFileId'])
    return episodes_to_delete

def delete_episodes_in_sonarr(episode_file_ids):
    """Delete specified episodes in Sonarr."""
    for episode_file_id in episode_file_ids:
        url = f"{SONARR_URL}/api/v3/episodeFile/{episode_file_id}"
        headers = {'X-Api-Key': SONARR_API_KEY}
        response = requests.delete(url, headers=headers)
        if response.ok:
            logging.info(f"Successfully deleted episode file with ID: {episode_file_id}")
        else:
            logging.error(f"Failed to delete episode file. Response: {response.text}")
def determine_keep_ids(current_episodes, episode_number, KEEP_WATCHED, ALWAYS_KEEP):
    # Keep the most recent episodes as specified by 'KEEP_WATCHED'
    if isinstance(KEEP_WATCHED, int):
        keep_ids = [ep['id'] for ep in sorted(current_episodes, key=lambda x: -x['episodeNumber'])[:KEEP_WATCHED]]
    else:
        # Keep all episodes in the current season if 'KEEP_WATCHED' is set to 'season'
        keep_ids = [ep['id'] for ep in current_episodes]

    # Ensure episodes with titles in 'ALWAYS_KEEP' are not deleted
    keep_ids.extend(ep['id'] for ep in current_episodes if ep['seriesTitle'] in ALWAYS_KEEP and ep['id'] not in keep_ids)
    return list(set(keep_ids))  # Remove duplicates and return the list

def main():
    series_name, season_number, episode_number = get_server_activity()
    if series_name:
        series_id = get_series_id(series_name)
        if series_id:
            current_season_episodes = get_episode_details(series_id, season_number)
            if current_season_episodes:
               # Unmonitor all episodes watched up to the current one
                unmonitor_ids = [ep['id'] for ep in current_season_episodes if ep['episodeNumber'] <= episode_number]
                logging.debug(f"IDs to unmonitor: {unmonitor_ids}")  # Debugging statement

                # Unmonitor episodes based on the IDs only if monitor_watched is False
                if not config['monitor_watched']:
                    unmonitor_episodes(unmonitor_ids)

                # Handling deletions based on configuration
                keep_ids = determine_keep_ids(current_season_episodes, episode_number, config['KEEP_WATCHED'], config['ALWAYS_KEEP'])
                episodes_to_delete = find_episodes_to_delete(current_season_episodes, episode_number)
                episodes_to_delete = [ep for ep in episodes_to_delete if ep['id'] not in keep_ids]
                delete_episodes_in_sonarr(episodes_to_delete)

                # Handling future episodes: monitor and potentially search based on action_option
                remaining_current_season = [ep for ep in current_season_episodes if ep['episodeNumber'] > episode_number]
                episodes_needed = config['get_option'] - len(remaining_current_season)
                next_episode_ids = [ep['id'] for ep in remaining_current_season][:config['get_option']]
                
                if episodes_needed > 0:
                    next_season_episodes = get_episode_details(series_id, season_number + 1)
                    if next_season_episodes:
                        additional_episodes_needed = config['get_option'] - len(next_episode_ids)
                        next_episode_ids.extend([ep['id'] for ep in next_season_episodes][:additional_episodes_needed])
                    else:
                        logging.info(f"No more seasons available after season {season_number} for series {series_name}.")

                monitor_episodes(next_episode_ids, monitor=True)
                if config['action_option'] == "search":
                    trigger_episode_search_in_sonarr(next_episode_ids)

            else:
                logging.info("No episodes found for the current series and season.")
        else:
            logging.error("Failed to fetch series ID for the active series.")
    else:
        logging.info("No active series found to process.")

if __name__ == "__main__":
    main()


