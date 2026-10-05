from slowapi import Limiter
from slowapi.util import get_remote_address

# ponytail: in-memory counters (one API process); switch storage_uri to Postgres/Redis if the API ever scales out
limiter = Limiter(key_func=get_remote_address)
