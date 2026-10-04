"""Reset state and load the 10 fictional customers."""
from app import db

if __name__ == "__main__":
    print(f"Seeded {db.reset_and_seed()} customers into {db.config.DB_PATH}")
