from __future__ import annotations

import warnings

REMOVAL_RELEASE = "0.6.0"


def warn_deprecated(
    subject: str, advice: str, *, stacklevel: int = 2, category: type[Warning] = DeprecationWarning
) -> None:
    """Warn that ``subject`` is deprecated, naming the package and the release that removes it.

    ``category`` is :class:`DeprecationWarning` when a replacement exists
    today, and :class:`PendingDeprecationWarning` when the replacement first
    ships in the release that removes ``subject``, so there is nothing to
    migrate to yet. ``stacklevel`` counts from the caller of this function, as
    it does for :func:`warnings.warn`.
    """
    warnings.warn(
        f"{subject} is deprecated and will be removed in sci-etl-core {REMOVAL_RELEASE}; {advice}",
        category,
        stacklevel=stacklevel + 1,
    )


def warn_advance_notice(subject: str, advice: str, *, stacklevel: int = 2) -> None:
    """Warn with a :class:`PendingDeprecationWarning` about a removal whose replacement is not released yet."""
    warn_deprecated(subject, advice, stacklevel=stacklevel + 1, category=PendingDeprecationWarning)


def is_bundled(cls: type) -> bool:
    """Whether ``cls`` is defined inside sci-etl-core itself."""
    return cls.__module__.partition(".")[0] == "sci_etl_core"


def warn_logger_argument(owner: str, logger: object, *, stacklevel: int = 3) -> None:
    """Give advance notice that ``owner``'s ``logger=`` argument goes in 0.6.0, when one was passed."""
    if logger is not None:
        warn_advance_notice(
            f"{owner}(logger=)",
            "0.6.0 logs through the standard logging module under the sci_etl_core logger",
            stacklevel=stacklevel,
        )
