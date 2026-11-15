DROP TABLE IF EXISTS registrations;
DROP TABLE IF EXISTS participants;
DROP TABLE IF EXISTS events;
DROP TABLE IF EXISTS users;

CREATE TABLE users (
    user_id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('Admin', 'Host'))
);

CREATE TABLE events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    event_date TEXT NOT NULL,
    venue TEXT NOT NULL,
    capacity INTEGER NOT NULL CHECK (capacity > 0),
    host_id INTEGER,
    FOREIGN KEY (host_id) REFERENCES users (user_id) ON DELETE SET NULL
);

CREATE TABLE participants (
    participant_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    contact TEXT NOT NULL UNIQUE,
    user_qr TEXT NOT NULL UNIQUE
);

CREATE TABLE registrations (
    registration_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL,
    participant_id INTEGER NOT NULL,
    attendance_status TEXT NOT NULL DEFAULT 'Absent' CHECK (attendance_status IN ('Present', 'Absent')),
    qr_code TEXT NOT NULL UNIQUE,
    FOREIGN KEY (event_id) REFERENCES events (event_id) ON DELETE CASCADE,
    FOREIGN KEY (participant_id) REFERENCES participants (participant_id) ON DELETE CASCADE,
    UNIQUE(event_id, participant_id)
);