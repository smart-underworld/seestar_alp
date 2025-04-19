import collections
import uuid
from typing import TypedDict, Literal

from device.seestar_util import Util
from pydantic import BaseModel, Field

type ScheduleState = Literal['working', 'stopped', 'stopping', 'paused', 'complete']


class Schedule(TypedDict):
    version: float
    Event: str
    schedule_id: str
    list: collections.deque
    state: str
    is_stacking_paused: bool
    is_stacking: bool
    is_skip_requested: bool
    current_item_id: str
    item_number: int

class ScheduleParams(BaseModel):
    pass

class ScheduleItem(BaseModel):
    schedule_item_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    action: str
    params: ScheduleParams


class Schedule2(BaseModel):
    version: float
    Event: str
    schedule_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    list: collections.deque
    state: ScheduleState
    is_stacking_paused: bool
    is_stacking: bool
    is_skip_requested: bool
    current_item_id: str
    item_number: int

    def create_schedule(self):
        return self

    def construct_schedule_item(self, params):
        item = params.copy()
        if item['action'] == 'start_mosaic':
            mosaic_params = item['params']
            if isinstance(mosaic_params['ra'], str):
                # try to trim the seconds to 1 decimal
                mosaic_params['ra'] = Util.trim_seconds(mosaic_params['ra'])
                mosaic_params['dec'] = Util.trim_seconds(mosaic_params['dec'])
            elif isinstance(mosaic_params['ra'], float):
                if mosaic_params['ra'] < 0:
                    mosaic_params['ra'] = self.ra
                    mosaic_params['dec'] = self.dec
                    mosaic_params['is_j2000'] = False
                mosaic_params['ra'] = round(mosaic_params['ra'], 4)
                mosaic_params['dec'] = round(mosaic_params['dec'], 4)
        item['schedule_item_id'] = str(uuid.uuid4())
        return item

    def add_schedule_item(self, params: dict[str, str]):
        return self

    def replace_schedule_item(self, params: dict[str, str]):
        return self

    def insert_schedule_item_before(self, params: dict[str, str]):
        return self

    def export_schedule(self, params: dict[str, str]):
        return self

    def import_schedule(self, params: dict[str, str]):
        return self

# todo:
# - add type for deque
# - create_schedule
# - add_schedule_item
# - replace_schedule_item
# - insert_schedule_item_before
# - export_schedule
# - import_schedule
