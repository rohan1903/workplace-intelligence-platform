"""
Shared demo meeting rooms for registration + admin.
Default department list for visitor registration (merged with employee records in Firebase).
"""

# Departments offered when the directory is empty; unioned with unique `department` values from employees.
DEFAULT_DEPARTMENT_OPTIONS = [
    "Engineering",
    "Operations",
    "Facilities",
    "Human Resources",
    "Finance",
    "Sales",
    "Legal",
    "Marketing",
    "Executive / Admin",
]

# Same room ids as registration merge; includes admin fields for /rooms UI.
PRESENTATION_ROOM_OPTIONS = {
    "_presentation_room_alpha": {
        "name": "Conference Room Alpha",
        "capacity": 8,
        "floor": "1",
        "amenities": "Demo listing (presentation)",
    },
    "_presentation_room_beta": {
        "name": "Board Room Beta",
        "capacity": 14,
        "floor": "2",
        "amenities": "Demo listing (presentation)",
    },
    "_presentation_room_gamma": {
        "name": "Huddle Space Gamma",
        "capacity": 4,
        "floor": "1",
        "amenities": "Demo listing (presentation)",
    },
}

PRESENTATION_ROOM_IDS = frozenset(PRESENTATION_ROOM_OPTIONS.keys())
