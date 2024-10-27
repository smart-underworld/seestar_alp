#
# Message tracing.
#
# Save messages in a sqlite3 file.  We create a SQLite database
#   per telescope and port for now to avoid concurrency issues.
#
import sqlite3
import threading
from contextlib import closing
from datetime import datetime

# x INTEGER PRIMARY KEY ASC

class MessageTrace:
    def __init__(self, telescope_id, port, do_save=True):
        self.telescope_id = telescope_id
        self.port = port
        self.lock = threading.RLock()
        self.do_save = do_save
        self.connection = sqlite3.connect(f"messages_{telescope_id}_{port}.db", check_same_thread=False)
        try:
            with self.lock:
                with closing(self.connection.cursor()) as cursor:
                    cursor.execute(
                        "CREATE TABLE messages (telescope_id INTEGER, port INTEGER, timestamp TEXT, type TEXT, data BLOB)")
        except:
            # we just ignore create table for now...
            print("table already exists")
            pass

    def save_message(self, message, direction):
        if self.do_save:
            with self.lock:
                with closing(self.connection.cursor()) as cursor:
                    cursor.execute("INSERT INTO messages VALUES(?, ?, ?, ?, ?)",
                                   (self.telescope_id, self.port, str(datetime.now()), direction, message,))
                self.connection.commit()

# Prune old data:  from messages where timestamp > datetime('now', 'localtime', '-5 minute') ;
