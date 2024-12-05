from pathlib import Path
import yaml
import requests
import json
from datetime import datetime
import gc
import gzip
import pickle
from tqdm import tqdm
import numpy as np
import time
import pandas as pd
import os
from dotenv import load_dotenv
import folium
import polyline
from typing import Union
import random

load_dotenv()

folder_path = Path("store")

ROUTE_COLORS = [
    '#FF6B6B', '#4ECDC4', '#45B7D1', '#96CEB4', '#FFEEAD',
    '#D4A5A5', '#9B59B6', '#3498DB', '#E74C3C', '#2ECC71',
    '#F1C40F', '#1ABC9C', '#E67E22', '#34495E', '#7F8C8D'
]

def convert_second_to_time_with_s(x):
    hours = int(x/3600)
    minutes = int(x % 3600 / 60)
    seconds = x - (hours * 3600 + minutes * 60)
    hours = str(hours)
    minutes = str(minutes)
    seconds = str(seconds)
    if len(hours) < 2:
        hours = "0" + hours
    if len(minutes) < 2:
        minutes = "0" + minutes
    if len(seconds) < 2:
        seconds = "0" + seconds

    return str(hours) + ":" + str(minutes) + ":" + str(seconds)


def save_pickle_quick(file_to_save, file_saving_path):
    gc.disable()
    try:
        gc.collect()
        with gzip.open(file_saving_path, "wb") as fp:
            pickle.dump(file_to_save, fp)
    finally:
        gc.enable()

class OneMapQuery:
    def __init__(self):
        """Initialize OneMapQuery and automatically get token"""
        self.token = None
        self.api_call_count = 0
        self.api_call_start_time = time.time()
        # Automatically get token on initialization
        self.get_onemap_token()

    def _check_rate_limit(self):
        # Check if 1 minute has passed since the start of the API call window
        if time.time() - self.api_call_start_time >= 60:
            self.api_call_count = 0
            self.api_call_start_time = time.time()

        # If the API call count exceeds the limit, wait until the minute is over
        if self.api_call_count >= 150:
            time_to_wait = 60 - (time.time() - self.api_call_start_time)
            print(f"Rate limit reached. Waiting for {time_to_wait:.2f} seconds.")
            time.sleep(time_to_wait)
            self.api_call_count = 0
            self.api_call_start_time = time.time()

    def get_postal_latlong(
            self, postal_code: str = None
    ) -> tuple[float, float] | None:
        """
        Get latitude and longitude for a given postal code
        Returns tuple of (latitude, longitude) or None if not found
        """
        self._check_rate_limit()
        self.api_call_count += 1
        with open(folder_path/'postal_dict.yaml', 'r') as yaml_file:
            postal_dict = yaml.load(yaml_file, Loader=yaml.Loader)

        url = f'https://www.onemap.gov.sg/api/common/elastic/search?' \
              f'searchVal={postal_code}&' \
              f'returnGeom=Y&' \
              f'getAddrDetails=Y' \
              f'&pageNum=1'

        try:
            resp = requests.get(url)
            resp.raise_for_status()
            content = resp.json()
            
            if content['found'] == 0:
                print(f"This postal: '{postal_code}' lat long is not found from onemap")
                return None

            result = content['results'][0]
            latlon = (float(result['LATITUDE']), float(result['LONGITUDE']))
            postal_dict[postal_code] = latlon

            with open(folder_path / 'postal_dict.yaml', 'w') as yaml_file:
                yaml.dump(postal_dict, yaml_file)

            return latlon

        except requests.exceptions.RequestException as e:
            print(f"Error fetching data from OneMap: {e}")
            return None

    def get_onemap_token(self):
        # Create store folder if it doesn't exist
        folder_path.mkdir(exist_ok=True)
        token_file = folder_path/'onemap_token.yaml'

        try:
            # Try to load existing token
            if token_file.exists():
                with open(token_file, 'r') as yaml_file:
                    content = yaml.load(yaml_file, Loader=yaml.FullLoader)
                    
                # Check if token is still valid (less than 3 days old)
                if content and (datetime.today() - datetime.fromtimestamp(int(content['expiry_timestamp']))).days < 3:
                    self.token = content['access_token']
                    return content['access_token']
        except Exception as e:
            print(f"Error reading token file: {e}")

        # Request new token if file doesn't exist or token expired
        url = 'https://www.onemap.gov.sg/api/auth/post/getToken'
        payload = {
            'email': os.getenv('ONEMAP_USERNAME'),
            'password': os.getenv('ONEMAP_PASSWORD')
        }
        
        try:
            resp = requests.post(url, json=payload)
            resp.raise_for_status()
            
            content = resp.json()
            self.token = content['access_token']
            
            # Save new token
            with open(token_file, 'w') as yaml_file:
                yaml.dump(content, yaml_file)
                
            return self.token
            
        except requests.exceptions.RequestException as e:
            raise Exception(f'Failed to get token. Error: {str(e)}')

    def get_address_by_postal(self, postal_code: str = None) -> str | None:
        """
        Get full address string for a given postal code
        Returns address string or None if not found
        """
        self._check_rate_limit()
        self.api_call_count += 1
        url = f'https://www.onemap.gov.sg/api/common/elastic/search?' \
              f'searchVal={postal_code}&' \
              f'returnGeom=Y&' \
              f'getAddrDetails=Y' \
              f'&pageNum=1'

        try:
            resp = requests.get(url)
            resp.raise_for_status()
            content = resp.json()
            
            if content['found'] == 0:
                print(f"No address found for postal code: '{postal_code}'")
                return None

            result = content['results'][0]
            address = result['ADDRESS']
            return address

        except requests.exceptions.RequestException as e:
            print(f"Error fetching data from OneMap: {e}")
            return None

    def plot_routes(self, start_latlong: tuple, end_latlong: tuple, map_obj: folium.Map, 
                    color_index: Union[int, None] = None, sequence: tuple[int, int] = None) -> None:
        """
        Plot a route between two points on a Folium map
        Args:
            start_latlong: Tuple of (latitude, longitude) for start point
            end_latlong: Tuple of (latitude, longitude) for end point
            map_obj: Folium map object to plot the route on
            color_index: Optional index for color selection (1-based index)
            sequence: Tuple of (start_sequence, end_sequence) numbers
        """
        # Ensure we have a valid token
        if not self.token:
            self.get_onemap_token()

        # Color selection logic
        if color_index is not None:
            color = ROUTE_COLORS[(color_index - 1) % len(ROUTE_COLORS)]
        else:
            color = random.choice(ROUTE_COLORS)

        # Format the coordinates for the URL
        start_coord = f"{start_latlong[0]},{start_latlong[1]}"
        end_coord = f"{end_latlong[0]},{end_latlong[1]}"
        
        url = f"https://www.onemap.gov.sg/api/public/routingsvc/route?" \
              f"start={start_coord}&end={end_coord}&routeType=drive"
        
        headers = {"Authorization": self.token}
        
        try:
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            route_data = response.json()
            
            if route_data['status'] == 0:  # Success
                # Decode the route geometry and add to map
                geometry = route_data['route_geometry']
                route_coords = polyline.decode(geometry)
                folium.PolyLine(locations=route_coords, color=color, weight=2).add_to(map_obj)
                
                # Add markers for start and end points with sequence numbers
                start_seq = f"Stop {sequence[0]}" if sequence else "Start"
                end_seq = f"Stop {sequence[1]}" if sequence else "End"
                
                folium.CircleMarker(
                    location=start_latlong,
                    popup=start_seq,
                    tooltip=start_seq,  # Add tooltip for hover effect
                    color=color,
                    fill=True,
                    fillColor=color,
                    radius=8
                ).add_to(map_obj)
                
                # Add a text label for the sequence number
                if sequence:
                    folium.map.Marker(
                        start_latlong,
                        icon=folium.DivIcon(
                            html=f'<div style="font-size: 12pt; color: {color}; text-align: center;">{sequence[0]}</div>'
                        )
                    ).add_to(map_obj)
                
                folium.CircleMarker(
                    location=end_latlong,
                    popup=end_seq,
                    tooltip=end_seq,  # Add tooltip for hover effect
                    color=color,
                    fill=True,
                    fillColor=color,
                    radius=8
                ).add_to(map_obj)
                
                # Add a text label for the sequence number
                if sequence:
                    folium.map.Marker(
                        end_latlong,
                        icon=folium.DivIcon(
                            html=f'<div style="font-size: 12pt; color: {color}; text-align: center;">{sequence[1]}</div>'
                        )
                    ).add_to(map_obj)
                
            else:
                print("Failed to get route data")
                
        except requests.exceptions.RequestException as e:
            print(f"Error fetching route data: {e}")

    def save_matrices(self, locations: list[tuple[float, float]], duration_matrix: np.ndarray, distance_matrix: np.ndarray):
        """
        Save duration and distance matrices along with their corresponding locations
        """
        matrices_data = {
            'locations': locations,
            'duration_matrix': duration_matrix.tolist(),
            'distance_matrix': distance_matrix.tolist()
        }
        
        save_pickle_quick(matrices_data, folder_path/'matrices_data.pkl.gz')

    def load_matrices(self) -> tuple[list[tuple[float, float]], np.ndarray, np.ndarray] | None:
        """
        Load existing matrices and their corresponding locations
        Returns:
            Tuple of (locations, duration_matrix, distance_matrix) or None if file doesn't exist
        """
        try:
            with gzip.open(folder_path/'matrices_data.pkl.gz', 'rb') as fp:
                matrices_data = pickle.load(fp)
                return (
                    matrices_data['locations'],
                    np.array(matrices_data['duration_matrix']),
                    np.array(matrices_data['distance_matrix'])
                )
        except (FileNotFoundError, EOFError):
            return None

    def expand_matrices(
        self,
        new_locations: list[tuple[float, float]]
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Load existing matrices and expand them with new locations
        Args:
            new_locations: List of new (latitude, longitude) tuples to add
        Returns:
            Updated (duration_matrix, distance_matrix)
        """
        # Load existing matrices
        existing_data = self.load_matrices()
        
        if existing_data is None:
            # If no existing matrices, create new ones from scratch
            return self.get_route_matrices(new_locations)
        
        existing_locations, duration_matrix, distance_matrix = existing_data
        
        # Find truly new locations (not already in matrix)
        new_locations_set = set(new_locations)
        existing_locations_set = set(existing_locations)
        locations_to_add = list(new_locations_set - existing_locations_set)
        
        if not locations_to_add:
            return duration_matrix, distance_matrix
        
        # Calculate size of expanded matrices
        old_size = len(existing_locations)
        new_size = old_size + len(locations_to_add)
        
        # Create expanded matrices
        new_duration_matrix = np.zeros((new_size, new_size))
        new_distance_matrix = np.zeros((new_size, new_size))
        
        # Copy existing matrices to new matrices
        new_duration_matrix[:old_size, :old_size] = duration_matrix
        new_distance_matrix[:old_size, :old_size] = distance_matrix
        
        # Calculate new routes for new locations
        print(f"Calculating routes for {len(locations_to_add)} new locations...")
        
        # First, calculate routes between new locations and existing locations
        with tqdm(total=len(locations_to_add) * old_size) as pbar:
            for i, new_loc in enumerate(locations_to_add):
                for j, existing_loc in enumerate(existing_locations):
                    self._check_rate_limit()
                    self.api_call_count += 1
                    
                    # Calculate route from new location to existing location
                    start_coord = f"{new_loc[0]},{new_loc[1]}"
                    end_coord = f"{existing_loc[0]},{existing_loc[1]}"
                    
                    url = f"https://www.onemap.gov.sg/api/public/routingsvc/route?" \
                          f"start={start_coord}&end={end_coord}&routeType=drive"
                    
                    try:
                        response = requests.get(url, headers={"Authorization": self.token})
                        response.raise_for_status()
                        route_data = response.json()
                        
                        if route_data['status'] == 0:  # Success
                            # Add values to both directions (matrix is symmetric)
                            new_duration_matrix[old_size + i, j] = route_data['route_summary']['total_time']
                            new_duration_matrix[j, old_size + i] = new_duration_matrix[old_size + i, j]
                            
                            new_distance_matrix[old_size + i, j] = route_data['route_summary']['total_distance']
                            new_distance_matrix[j, old_size + i] = new_distance_matrix[old_size + i, j]
                        else:
                            # Set to infinity for failed routes
                            new_duration_matrix[old_size + i, j] = float('inf')
                            new_duration_matrix[j, old_size + i] = float('inf')
                            new_distance_matrix[old_size + i, j] = float('inf')
                            new_distance_matrix[j, old_size + i] = float('inf')
                            print(f"Failed to get route data between points {old_size + i} and {j}")
                    except Exception as e:
                        # Set to infinity for failed routes
                        new_duration_matrix[old_size + i, j] = float('inf')
                        new_duration_matrix[j, old_size + i] = float('inf')
                        new_distance_matrix[old_size + i, j] = float('inf')
                        new_distance_matrix[j, old_size + i] = float('inf')
                        print(f"Error calculating route between points {old_size + i} and {j}: {e}")
                    
                    pbar.update(1)
                    time.sleep(0.5)  # Add delay to avoid hitting rate limits
        
        # Calculate routes between new locations
        with tqdm(total=(len(locations_to_add) * (len(locations_to_add) - 1)) // 2) as pbar:
            for i in range(len(locations_to_add)):
                for j in range(i + 1, len(locations_to_add)):
                    self._check_rate_limit()
                    self.api_call_count += 1
                    
                    start_coord = f"{locations_to_add[i][0]},{locations_to_add[i][1]}"
                    end_coord = f"{locations_to_add[j][0]},{locations_to_add[j][1]}"
                    
                    url = f"https://www.onemap.gov.sg/api/public/routingsvc/route?" \
                          f"start={start_coord}&end={end_coord}&routeType=drive"
                    
                    try:
                        response = requests.get(url, headers={"Authorization": self.token})
                        response.raise_for_status()
                        route_data = response.json()
                        
                        if route_data['status'] == 0:  # Success
                            # Add values to both directions (matrix is symmetric)
                            new_duration_matrix[old_size + i, old_size + j] = route_data['route_summary']['total_time']
                            new_duration_matrix[old_size + j, old_size + i] = new_duration_matrix[old_size + i, old_size + j]
                            
                            new_distance_matrix[old_size + i, old_size + j] = route_data['route_summary']['total_distance']
                            new_distance_matrix[old_size + j, old_size + i] = new_distance_matrix[old_size + i, old_size + j]
                        else:
                            # Set to infinity for failed routes
                            new_duration_matrix[old_size + i, old_size + j] = float('inf')
                            new_duration_matrix[old_size + j, old_size + i] = float('inf')
                            new_distance_matrix[old_size + i, old_size + j] = float('inf')
                            new_distance_matrix[old_size + j, old_size + i] = float('inf')
                            print(f"Failed to get route data between points {old_size + i} and {old_size + j}")
                    except Exception as e:
                        # Set to infinity for failed routes
                        new_duration_matrix[old_size + i, old_size + j] = float('inf')
                        new_duration_matrix[old_size + j, old_size + i] = float('inf')
                        new_distance_matrix[old_size + i, old_size + j] = float('inf')
                        new_distance_matrix[old_size + j, old_size + i] = float('inf')
                        print(f"Error calculating route between points {old_size + i} and {old_size + j}: {e}")
                    
                    pbar.update(1)
                    time.sleep(0.5)  # Add delay to avoid hitting rate limits
        
        # Save expanded matrices
        all_locations = existing_locations + locations_to_add
        self.save_matrices(all_locations, new_duration_matrix, new_distance_matrix)
        
        return new_duration_matrix, new_distance_matrix

    def get_route_matrices(self, locations: list[tuple[float, float]]) -> tuple[np.ndarray, np.ndarray]:
        """
        Get duration and distance matrices for a list of locations, using cached data when possible
        """
        # Ensure we have a valid token before starting
        if not self.token:
            self.get_onemap_token()

        # Try to load existing matrices and expand if needed
        existing_data = self.load_matrices()
        
        if existing_data is not None:
            existing_locations, duration_matrix, distance_matrix = existing_data
            existing_locations_set = set(existing_locations)
            new_locations_set = set(locations)
            
            # If we have new locations, expand the matrices
            if not new_locations_set.issubset(existing_locations_set):
                return self.expand_matrices(locations)
            
            # If all locations exist in current matrices, create view matrices
            location_indices = [existing_locations.index(loc) for loc in locations]
            return (
                duration_matrix[np.ix_(location_indices, location_indices)],
                distance_matrix[np.ix_(location_indices, location_indices)]
            )
        
        # If no existing matrices, calculate from scratch
        n = len(locations)
        duration_matrix = np.zeros((n, n))
        distance_matrix = np.zeros((n, n))
        
        # Create progress bar for total number of calculations
        total_calculations = (n * n - n) // 2  # Only need to calculate upper triangle
        with tqdm(total=total_calculations, desc="Calculating matrices") as pbar:
            for i in range(n):
                for j in range(i + 1, n):  # Only calculate upper triangle
                    self._check_rate_limit()
                    self.api_call_count += 1
                    
                    start_coord = f"{locations[i][0]},{locations[i][1]}"
                    end_coord = f"{locations[j][0]},{locations[j][1]}"
                    
                    url = f"https://www.onemap.gov.sg/api/public/routingsvc/route?" \
                          f"start={start_coord}&end={end_coord}&routeType=drive"
                    
                    try:
                        response = requests.get(url, headers={"Authorization": self.token})
                        response.raise_for_status()
                        route_data = response.json()
                        
                        if route_data['status'] == 0:  # Success
                            duration_matrix[i, j] = route_data['route_summary']['total_time']
                            duration_matrix[j, i] = duration_matrix[i, j]  # Matrix is symmetric
                            
                            distance_matrix[i, j] = route_data['route_summary']['total_distance']
                            distance_matrix[j, i] = distance_matrix[i, j]  # Matrix is symmetric
                        else:
                            print(f"Failed to get route data for points {i} to {j}")
                            
                    except requests.exceptions.RequestException as e:
                        print(f"Error fetching route data for points {i} to {j}: {e}")
                    
                    pbar.update(1)
                    time.sleep(0.5)  # Add delay to avoid hitting rate limits
        
        # Save matrices
        self.save_matrices(locations, duration_matrix, distance_matrix)
        
        return duration_matrix, distance_matrix

    def update_zero_cells(self, duration_matrix: np.ndarray, distance_matrix: np.ndarray, locations: list[tuple[float, float]]):
        """
        Check for zero values in non-diagonal cells and update them by calling the API again.
        """
        n = len(locations)
        for i in range(n):
            for j in range(n):
                if i != j and duration_matrix[i, j] == 0:
                    self._check_rate_limit()
                    self.api_call_count += 1

                    start_coord = f"{locations[i][0]},{locations[i][1]}"
                    end_coord = f"{locations[j][0]},{locations[j][1]}"
                    
                    url = f"https://www.onemap.gov.sg/api/public/routingsvc/route?" \
                          f"start={start_coord}&end={end_coord}&routeType=drive"
                    
                    try:
                        response = requests.get(url, headers={"Authorization": self.token})
                        response.raise_for_status()
                        route_data = response.json()
                        
                        if route_data['status'] == 0:  # Success
                            duration_matrix[i, j] = route_data['route_summary']['total_time']
                            distance_matrix[i, j] = route_data['route_summary']['total_distance']
                        else:
                            print(f"Failed to update route data for points {i} to {j}")
                    except Exception as e:
                        print(f"Error updating route data for points {i} to {j}: {e}")

    def update_inf_cells(self, duration_matrix: np.ndarray, distance_matrix: np.ndarray, locations: list[tuple[float, float]]):
        """
        Check for inf values in the matrices and update them by calling the API again.
        """
        n = len(locations)
        for i in range(n):
            for j in range(n):
                if i != j and (duration_matrix[i, j] == float('inf') or distance_matrix[i, j] == float('inf')):
                    self._check_rate_limit()
                    self.api_call_count += 1

                    start_coord = f"{locations[i][0]},{locations[i][1]}"
                    end_coord = f"{locations[j][0]},{locations[j][1]}"
                    
                    url = f"https://www.onemap.gov.sg/api/public/routingsvc/route?" \
                          f"start={start_coord}&end={end_coord}&routeType=drive"
                    
                    try:
                        response = requests.get(url, headers={"Authorization": self.token})
                        response.raise_for_status()
                        route_data = response.json()
                        
                        if route_data['status'] == 0:  # Success
                            duration_matrix[i, j] = route_data['route_summary']['total_time']
                            distance_matrix[i, j] = route_data['route_summary']['total_distance']
                        else:
                            print(f"Failed to update route data for points {i} to {j}")
                    except Exception as e:
                        print(f"Error updating route data for points {i} to {j}: {e}")


if __name__ == "__main__":
    om = OneMapQuery()
    om.get_onemap_token()
    om.get_postal_latlong(338729)
    om.get_address_by_postal(641183)
    m = folium.Map(location=[1.352083, 103.819839], zoom_start=12, tiles="cartodbpositron")
    start = (1.319728, 103.8421)
    end = (1.299728905, 103.8421581)
    om.plot_routes(start, end, m, 1, ("start",1))
    start = (1.299728905, 103.8421581)
    end = (1.3236092349281756, 103.63496008940602)
    om.plot_routes(start, end, m, 1, (1,"end"))
    m.save('route_map.html')
    locations = [
        (1.319728, 103.8421),
        (1.299728905, 103.8421581),
        (1.3236092349281756, 103.63496008940602)
    ]
    duration_matrix, distance_matrix = om.get_route_matrices(locations)

    # Print matrices in a readable format
    print("Duration Matrix")
    print(duration_matrix)

    print("\nDistance Matrix")
    print(distance_matrix)

    locations = [
        (1.319728, 103.8421),
        (1.299728905, 103.8421581),
        (1.3236092349281756, 103.63496008940602),
        (1.352083, 103.819839)
    ]
    duration_matrix, distance_matrix = om.get_route_matrices(locations)

    # Print matrices in a readable format
    print("Duration Matrix (in HH:MM:SS):")
    print(duration_matrix)

    print("\nDistance Matrix (in meters):")
    print(distance_matrix)
