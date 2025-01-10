"""Abstract Seestar imager.

This is a very narrowly defined abstract class."""

from abc import ABC, abstractmethod


class AbstractImager(ABC):
    @abstractmethod
    def get_frame(self):
        pass

    @abstractmethod
    def get_live_status(self):
        pass
