from __future__ import annotations

import warnings

REMOVAL_RELEASE = "0.6.0"


def warn_deprecated(subject: str, advice: str, *, stacklevel: int = 2) -> None:
    """Emit a :class:`DeprecationWarning` that names the package and the release removing ``subject``.

    ``stacklevel`` counts from the caller of this function, as it does for
    :func:`warnings.warn`.
    """
    warnings.warn(
        f"{subject} is deprecated and will be removed in sci-etl-core {REMOVAL_RELEASE}; {advice}",
        DeprecationWarning,
        stacklevel=stacklevel + 1,
    )


def is_bundled(cls: type) -> bool:
    """Whether ``cls`` is defined inside sci-etl-core itself."""
    return cls.__module__.partition(".")[0] == "sci_etl_core"


def warn_logger_argument(owner: str, logger: object, *, stacklevel: int = 3) -> None:
    """Warn that ``owner``'s ``logger=`` argument is deprecated, when one was passed."""
    if logger is not None:
        warn_deprecated(
            f"{owner}(logger=)",
            "0.6.0 logs through the standard logging module under the sci_etl_core logger",
            stacklevel=stacklevel,
        )
