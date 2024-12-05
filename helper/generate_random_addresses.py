import pandas as pd
import random
from pathlib import Path
import yaml
from helper.onemap import OneMapQuery
from datetime import datetime, timedelta

def generate_random_time():
    """Generate a random time window between 07:00:00 and 22:00:00"""
    # Convert time bounds to minutes since midnight
    start_bound = 7 * 60  # 07:00:00
    end_bound = 22 * 60   # 22:00:00
    
    # Generate two random times in minutes
    time1 = random.randint(start_bound, end_bound)
    time2 = random.randint(time1, end_bound)  # Ensure second time is later
    
    # Convert minutes to time strings
    time1_str = f"{time1//60:02d}:{time1%60:02d}:00"
    time2_str = f"{time2//60:02d}:{time2%60:02d}:00"
    
    return [time1_str, time2_str]

def generate_random_addresses(
    num_addresses: int = 30,
    time_windows: bool = False,
    output_path: Path = None,
    random_seed: int = 42,
    pickup: bool = False
) -> None:
    """
    Generate random addresses using postal codes from postal_dict.yaml
    and save them to an Excel file. If pickup=True, generates pairs of
    pickup and delivery addresses with time windows.
    """
    # Set random seed
    random.seed(random_seed)
    
    # Initialize OneMapQuery
    om = OneMapQuery()
    om.get_onemap_token()
    
    # Load postal codes from yaml file
    store_path = Path("store")
    with open(store_path/'postal_dict.yaml', 'r') as yaml_file:
        postal_dict = yaml.load(yaml_file, Loader=yaml.Loader)
    
    # Get list of postal codes (excluding None values)
    postal_codes = [k for k in postal_dict.keys() if isinstance(k, (str, int))]
    
    # Randomly select postal codes
    selected_codes = random.sample(postal_codes, num_addresses)
    
    # Generate addresses
    addresses = []
    if pickup:
        # Generate pairs of addresses for pickup/delivery
        for i in range(1, num_addresses + 1):
            # Select two different postal codes for pickup and delivery
            pickup_postal, delivery_postal = random.sample(postal_codes, 2)
            
            pickup_address = om.get_address_by_postal(str(pickup_postal))
            delivery_address = om.get_address_by_postal(str(delivery_postal))
            
            if pickup_address and delivery_address:
                # Generate sequential time windows for pickup and delivery
                if time_windows:
                    pickup_window = generate_random_time()
                    pickup_start = datetime.strptime(pickup_window[0], "%H:%M:%S")
                    
                    # Ensure delivery window starts after pickup window starts
                    delivery_window = generate_random_time()
                    delivery_start = datetime.strptime(delivery_window[0], "%H:%M:%S")
                    delivery_end = datetime.strptime(delivery_window[1], "%H:%M:%S")
                    
                    # If delivery start is earlier than pickup start, regenerate delivery window
                    while delivery_start < pickup_start:
                        delivery_window = generate_random_time()
                        delivery_start = datetime.strptime(delivery_window[0], "%H:%M:%S")
                        delivery_end = datetime.strptime(delivery_window[1], "%H:%M:%S")
                
                addresses.append({
                    'job_id': i,
                    'pickup_address': pickup_address,
                    'delivery_address': delivery_address,
                    'pickup_time_window': pickup_window if time_windows else None,
                    'delivery_time_window': delivery_window if time_windows else None
                })
    else:
        # Generate single random addresses
        for i in range(1, num_addresses + 1):
            # Select a random postal code
            postal_code = random.choice(postal_codes)
            
            # Get the address for the selected postal code
            address = om.get_address_by_postal(str(postal_code))
            
            if address:
                addresses.append({
                    'job_id': i,
                    'address': address,
                    'time_window': generate_random_time() if time_windows else None
                })

    # Create DataFrame
    df = pd.DataFrame(addresses)
    
    # Add time windows if requested
    if time_windows and not pickup:
        df['time_window'] = [generate_random_time() for _ in range(len(df))]
    
    # Use provided output path or default
    if output_path is None:
        output_path = store_path/'data'/'travelling_salesman.xlsx'
    
    # Create directory if it doesn't exist
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Save to Excel
    df.to_excel(output_path, index=False)


if __name__ == "__main__":
    # Example usage with pickup and delivery
    generate_random_addresses(
        num_addresses=30,
        time_windows=True,
        pickup=True,
        output_path=Path("store/data/pickup_delivery_jobs.xlsx")
    )
