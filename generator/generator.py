import random
import math
from datetime import datetime, timedelta
from faker import Faker

fake = Faker()
Faker.seed(42)
random.seed(42)


# Indian cities with approximate lat/lon - simulates the device/IP derived
# location a real PSP would attach to each transaction.
CITIES = {
    "Delhi":      (28.6139, 77.2090),
    "Mumbai":     (19.0760, 72.8777),
    "Bengaluru":  (12.9716, 77.5946),
    "Chennai":    (13.0827, 80.2707),
    "Kolkata":    (22.5726, 88.3639),
    "Hyderabad":  (17.3850, 78.4867),
    "Pune":       (18.5204, 73.8567),
    "Ahmedabad":  (23.0225, 72.5714),
    "Jaipur":     (26.9124, 75.7873),
    "Lucknow":    (26.8467, 80.9462),
    "Dehradun":   (30.3165, 78.0322),
    "Ghaziabad":  (28.6692, 77.4538),
}

CITY_NAMES = list(CITIES.keys())

# Merchant categories. Real networks use MCC codes; UPI PSPs carry similar
# merchant category data. Some categories carry far higher fraud risk.
CATEGORY_RISK = {
    "grocery":      0.0,
    "fuel":         0.0,
    "utilities":    0.0,
    "restaurant":   0.0,
    "retail":       0.0,
    "p2p":          0.0,
    "gaming":       0.6,
    "crypto":       0.9,
    "investment":   0.8,
    "forex":        0.7,
}

LOW_RISK_CATEGORIES = ["grocery", "fuel", "utilities", "restaurant", "retail", "p2p"]
HIGH_RISK_CATEGORIES = ["gaming", "crypto", "investment", "forex"]

# P2M (grocery/fuel/utilities/restaurant/retail) vs. P2P ("p2p") weighted to
# NPCI's reported 63/37 merchant-vs-peer transaction split. See CALIBRATION.md.
P2M_P2P_WEIGHTS = [0.126, 0.126, 0.126, 0.126, 0.126, 0.37]

# Amount bands (rupees) and their selection weights for everyday transactions.
# Weights are chosen so the blended mean lands on NPCI's published average
# UPI ticket size (~Rs 1,300). See CALIBRATION.md.
NORMAL_AMOUNT_BANDS = [(20, 500), (500, 5000), (5000, 20000)]
NORMAL_AMOUNT_WEIGHTS = [0.62, 0.37, 0.01]


def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance between two lat/lon points, in km."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(dlon / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(a))


def jitter_coords(lat, lon, km=8):
    dlat = random.uniform(-km, km) / 111.0
    dlon = random.uniform(-km, km) / (111.0 * math.cos(math.radians(lat)) + 1e-9)
    return round(lat + dlat, 5), round(lon + dlon, 5)


def make_vpa(name: str) -> str:
    return f"{name.lower().replace(' ', '.')}@upi"


class UserPool:
    """Fake UPI users. Each has a home city - normal people mostly transact
    from near home."""

    def __init__(self, initial_size=200):
        self.users = []
        self.home_city = {}
        self.active_trip = {}
        for _ in range(initial_size):
            self._add_user()

    def _add_user(self, vpa=None):
        vpa = vpa or make_vpa(fake.user_name())
        self.users.append(vpa)
        self.home_city[vpa] = random.choice(CITY_NAMES)
        return vpa

    def random_user(self):
        return random.choice(self.users)

    def new_user(self):
        return self._add_user(make_vpa(fake.user_name() + str(random.randint(1000, 9999))))

    def location_for(self, vpa, day=0, trip_prob=0.03):
        """Realistic location behaviour.

        Real people do not teleport between cities transaction by transaction.
        They are at home almost always, and occasionally take a TRIP - moving
        to another city and staying there for several days before returning.
        Modelling it per-transaction would manufacture fake "impossible
        travel" for ordinary users and drown the detector in false positives.
        """
        home = self.home_city.get(vpa, random.choice(CITY_NAMES))

        trip = self.active_trip.get(vpa)
        if trip is not None:
            trip_city, start_day, length = trip
            if start_day <= day < start_day + length:
                city = trip_city
            else:
                del self.active_trip[vpa]
                city = home
        else:
            if random.random() < trip_prob:
                trip_city = random.choice([c for c in CITY_NAMES if c != home])
                length = random.randint(2, 6)
                self.active_trip[vpa] = (trip_city, day, length)
                city = trip_city
            else:
                city = home

        lat, lon = CITIES[city]
        lat, lon = jitter_coords(lat, lon)
        return city, lat, lon


def generate_normal_transaction(pool: UserPool, base_time: datetime, day: int = 0) -> dict:
    """Everyday UPI transaction. Noisy amounts, human timing, mostly low-risk
    categories, near home."""
    sender = pool.random_user()
    receiver = pool.random_user()
    while receiver == sender:
        receiver = pool.random_user()

    band = random.choices(NORMAL_AMOUNT_BANDS, weights=NORMAL_AMOUNT_WEIGHTS)[0]
    amount = round(random.uniform(*band), 2)

    # Normal users occasionally use gaming/crypto too, so it isn't a
    # trivial giveaway for the model.
    if random.random() < 0.05:
        category = random.choice(HIGH_RISK_CATEGORIES)
    else:
        category = random.choices(LOW_RISK_CATEGORIES, weights=P2M_P2P_WEIGHTS)[0]

    city, lat, lon = pool.location_for(sender, day=day)

    jitter = timedelta(
        hours=random.uniform(0, 23),
        minutes=random.uniform(0, 59),
        seconds=random.uniform(0, 59),
    )

    return {
        "sender": sender,
        "receiver": receiver,
        "amount": amount,
        "type": random.choice(["deposit", "payout"]),
        "timestamp": (base_time + jitter).isoformat(),
        "is_scam": False,
        "scheme_id": None,
        "category": category,
        "city": city,
        "lat": lat,
        "lon": lon,
    }


class ScamScheme:
    """Ponzi/HYIP ring: receives deposits from a growing pool of new senders,
    pays back a near-fixed percentage on a near-fixed schedule, routed through
    high-risk categories, operated from scattered locations (mule network)."""

    def __init__(self, scheme_id: str, pool: UserPool, payout_ratio=None, day_offset=0):
        self.scheme_id = scheme_id
        self.pool = pool
        self.scheme_account = make_vpa(f"scheme-{scheme_id}")
        self.payout_ratio = payout_ratio or random.uniform(0.05, 0.10)
        self.members = []
        self.day_offset = day_offset
        self.category = random.choice(["crypto", "investment", "gaming"])

    def _scattered_location(self):
        """Operator appears from a different city almost every time - this is
        the impossible-travel signal."""
        city = random.choice(CITY_NAMES)
        lat, lon = CITIES[city]
        lat, lon = jitter_coords(lat, lon)
        return city, lat, lon

    def onboard_new_members(self, day: int, base_time: datetime, count=None):
        count = count or max(1, int(2 + day * 1.5))
        txs = []
        for _ in range(count):
            victim = self.pool.new_user()
            # Range calibrated so the average net loss (deposit x (1 - payout_ratio))
            # matches the Finance Ministry's reported ~Rs 7,566 average UPI fraud
            # loss per incident. See CALIBRATION.md.
            deposit_amount = round(random.uniform(3000, 13000), 2)
            jitter = timedelta(hours=random.uniform(9, 21), minutes=random.uniform(0, 59))
            ts = base_time + timedelta(days=day) + jitter
            self.members.append((victim, deposit_amount, day))
            v_city, v_lat, v_lon = self.pool.location_for(victim, day=day)
            txs.append({
                "sender": victim,
                "receiver": self.scheme_account,
                "amount": deposit_amount,
                "type": "deposit",
                "timestamp": ts.isoformat(),
                "is_scam": True,
                "scheme_id": self.scheme_id,
                "category": self.category,
                "city": v_city,
                "lat": v_lat,
                "lon": v_lon,
            })
        return txs

    def daily_payouts(self, day: int, base_time: datetime):
        txs = []
        payout_hour = 10 + (hash(self.scheme_id) % 3)
        for victim, deposit_amount, deposit_day in self.members:
            if deposit_day >= day:
                continue
            payout_amount = round(deposit_amount * self.payout_ratio, 2)
            jitter = timedelta(minutes=random.uniform(-5, 5))
            ts = base_time + timedelta(days=day) + timedelta(hours=payout_hour) + jitter
            city, lat, lon = self._scattered_location()
            txs.append({
                "sender": self.scheme_account,
                "receiver": victim,
                "amount": payout_amount,
                "type": "payout",
                "timestamp": ts.isoformat(),
                "is_scam": True,
                "scheme_id": self.scheme_id,
                "category": self.category,
                "city": city,
                "lat": lat,
                "lon": lon,
            })
        return txs


def generate_dataset(num_days=14, normal_txns_per_day=400, num_schemes=3):
    # Default of 400/day for a 300-user pool approximates NPCI's reported
    # ~1.33 transactions/user/day (national daily volume / active users).
    # See CALIBRATION.md.
    pool = UserPool(initial_size=300)
    base_time = datetime(2026, 8, 1)
    all_txns = []

    schemes = [ScamScheme(f"S{i+1}", pool, day_offset=i) for i in range(num_schemes)]

    for day in range(num_days):
        day_time = base_time + timedelta(days=day)

        for _ in range(normal_txns_per_day):
            all_txns.append(generate_normal_transaction(pool, day_time, day=day))

        for scheme in schemes:
            if day >= scheme.day_offset:
                all_txns.extend(scheme.onboard_new_members(day - scheme.day_offset, base_time))
                all_txns.extend(scheme.daily_payouts(day - scheme.day_offset, base_time))

    all_txns.sort(key=lambda t: t["timestamp"])
    return all_txns


if __name__ == "__main__":
    data = generate_dataset()
    scam_count = sum(1 for t in data if t["is_scam"])
    print(f"Generated {len(data)} transactions, {scam_count} scam-labeled "
          f"({scam_count/len(data)*100:.1f}%)")
    print(f"Sample: {data[0]}")
