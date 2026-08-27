"""Failure modes the pipeline is allowed to have.

Every one of these means "a fact is missing or a value is impossible", never
"substitute a plausible number and carry on". SPEC.md: do not fill a gap by
inference and move on.
"""


class SunupError(Exception):
    """Base class."""


class FixtureNotFound(SunupError):
    """A required raw payload is not on disk and live calls are disabled."""


class OfflineDataUnavailable(SunupError):
    """A data source exists in the design but has no cached payload yet.

    Raised instead of substituting a guess. The message must name the exact
    call that would fill the gap.
    """


class ImplausibleValue(SunupError):
    """A computed value fell outside its physical sanity band, a bug, not weather."""


class ConvergenceError(SunupError):
    """An iterative solve failed to bracket or converge."""


class CacheMiss(SunupError):
    """No cached response for this exact request.

    Not necessarily fatal: the client catches it and goes live when a live
    transport is configured. It IS fatal in the demo, where the transport
    refuses.
    """


class LiveCallBlocked(SunupError):
    """A live call was attempted while the offline transport was installed.

    SPEC.md hard constraint 6. Better a loud failure naming the missing fixture
    than a demo that hangs on a socket in front of an audience.
    """


class ActivityFailed(SunupError):
    """The API reported terminal status `Failed`. Failed tasks are free."""


class PollTimeout(SunupError):
    """An activity never reached a terminal status inside the poll budget.

    The activity_id is included: a submitted activity has already been paid for,
    so it should be retrieved rather than resubmitted.
    """


class ForbiddenInput(SunupError):
    """An input constants.py section 7 forbids was offered to the model.

    Age, sex, BMI, fitness, medical history, hydration, residence. The reason is
    legal, not stylistic: restricting a worker's hours on any of these is
    discrimination or ADA exposure. Refuse loudly; never accept and ignore.
    """
