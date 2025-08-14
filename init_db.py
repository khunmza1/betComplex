from app import app, db

with app.app_context():
    # drop all tables to ensure a clean slate
    db.drop_all()
    # create all tables with the new schema
    db.create_all()

print("Database initialized successfully.")
