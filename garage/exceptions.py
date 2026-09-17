class GarageError(Exception):
    """Base class for all garage-related errors."""


class GarageFullError(GarageError):
    """Raised when there is no available spot for a vehicle type."""


class SpotNotFoundError(GarageError):
    pass


class SpotAlreadyOccupiedError(GarageError):
    """Guards against ever double-parking a spot."""


class VehicleAlreadyParkedError(GarageError):
    """A plate can only have one active ticket at a time."""


class TicketNotFoundError(GarageError):
    """No active ticket exists for the given plate / ticket id."""


class InvalidTransferError(GarageError):
    """Raised for a malformed valet hand-off request (blank/same plate)."""


class RateCardImportError(GarageError):
    """Raised when a rate card file/source can't be cleaned into usable rates."""
