"""Business API dependency construction."""

from functools import partial

from toolwatch.application.ports import UnitOfWorkFactory
from toolwatch.infrastructure.database.engine import get_session_factory
from toolwatch.infrastructure.repositories import SqlAlchemyUnitOfWork


def get_uow_factory() -> UnitOfWorkFactory:
    """Construct units of work lazily from the process session factory."""

    return partial(SqlAlchemyUnitOfWork, get_session_factory())
