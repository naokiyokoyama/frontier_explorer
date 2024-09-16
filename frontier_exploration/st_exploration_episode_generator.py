from __future__ import annotations

import glob
import hashlib
import json
import os
from dataclasses import dataclass
from typing import Any, Optional

import cv2
import numpy as np
from habitat import EmbodiedTask, registry
from habitat.sims.habitat_simulator.habitat_simulator import HabitatSim
from hydra.core.config_store import ConfigStore
from omegaconf import DictConfig

from frontier_exploration.base_explorer import (
    BaseExplorer,
    BaseExplorerSensorConfig,
)
from frontier_exploration.utils.general_utils import images_to_video


@registry.register_sensor
class STEpisodeGenerator(BaseExplorer):
    cls_uuid: str = "st_exploration_episode_generator"

    def __init__(
        self, sim: "HabitatSim", config: "DictConfig", *args: Any, **kwargs: Any
    ) -> None:
        super().__init__(sim, config, *args, **kwargs)
        self._output_dir = config.output_dir
        self._num_episodes = config.num_episodes
        self._exploration_data = ExplorationData()

    @property
    def _is_last_episode_valid(self) -> bool:
        return len(self._exploration_data) > 10

    def _reset(self, episode) -> None:
        if self._is_last_episode_valid:
            self._save_last_episode()
        else:
            print("Last episode was too short, not saving it")

        super()._reset(episode)  # noqa

        self._exploration_data = ExplorationData()

    def _save_last_episode(self) -> None:
        map_filename = os.path.join(
            self._output_dir,
            self._scene_id,
            "topdown_maps",
            f"{hash_2d_binary_array(self.top_down_map)}.npy",
        )
        self._exploration_data.set_ids(
            self._episode.episode_id, self._scene_id, map_filename
        )

        # If the map is new, save it
        if not os.path.isfile(map_filename):
            save_map(self.top_down_map, str(map_filename))

        # Save the rest of the info needed
        # - Trajectory that the agent took (in global coords)
        # - Trajectory that the agent took (in pixel coords)
        # - Which topdown map was used (map_filename)
        # - Which scene_id was used (last_ep_scene_id)
        # - Which episode was used (last_ep_id)
        # - The RGB images recorded
        scene_dir = os.path.join(self._output_dir, self._scene_id)
        episode_dir = os.path.join(scene_dir, str(self._episode.episode_id))  # noqa

        # Quit if we have already saved self._num_episodes amount of episodes
        # for the current scene
        num_done = len(glob.glob(os.path.join(scene_dir, "*/")))  # noqa
        if num_done >= self._num_episodes:
            print(f"Already saved {self._num_episodes} episodes for {self._scene_id}")
            quit()
        else:
            print(
                f"Saved {num_done} of {self._num_episodes} episodes for "
                f"{self._scene_id}"
            )

        self._exploration_data.record(str(episode_dir))
        print(f"Saved episode {self._episode.episode_id} in {episode_dir}")

    def get_observation(
        self, task: EmbodiedTask, episode, *args: Any, **kwargs: Any
    ) -> np.ndarray:
        action = super().get_observation(task, episode, *args, **kwargs)
        self._exploration_data.append(
            kwargs["observations"]["rgb"],
            self._curr_pose,
            self._get_agent_pixel_coords(),
        )
        return action


class ExplorationData:
    def __init__(self):
        self._rgb_images = []
        self._trajectory = []
        self._trajectory_pixels = []
        self._ep_id: Optional[int] = None
        self._ep_scene_id: Optional[str] = None
        self._map_filename: Optional[str] = None

    def __len__(self):
        return len(self._rgb_images)

    def set_ids(self, ep_id, ep_scene_id, map_filename):
        self._ep_id = ep_id
        self._ep_scene_id = ep_scene_id
        self._map_filename = map_filename

    def append(self, rgb_image: np.ndarray, pose: list[float], pose_pixel: np.ndarray):
        self._rgb_images.append(rgb_image)
        self._trajectory.append(pose)
        self._trajectory_pixels.append(pose_pixel.tolist())

    def record(self, episode_directory: str):
        assert (
            len(self._rgb_images)
            == len(self._trajectory)
            == len(self._trajectory_pixels)
        )
        assert None not in [self._ep_id, self._ep_scene_id, self._map_filename]

        if not os.path.exists(episode_directory):
            os.makedirs(episode_directory)

        json_path = os.path.join(
            episode_directory, f"{self._ep_scene_id}_{self._ep_id}.json"
        )
        with open(json_path, "w") as f:
            json.dump(
                {
                    "ep_id": self._ep_id,
                    "ep_scene_id": self._ep_scene_id,
                    "trajectory": self._trajectory,
                    "trajectory_pixels": self._trajectory_pixels,
                    "map_filename": self._map_filename,
                },
                f,
            )

        # Save images as video for better compression
        video_path = os.path.join(episode_directory, "video.mp4")
        images_to_video(self._rgb_images, video_path)


def save_map(np_arr, filepath: str) -> None:
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    packed_mask = np.packbits(np_arr)
    np.save(filepath, packed_mask)


def hash_2d_binary_array(arr):
    arr_shape = arr.shape
    # Flatten the array and convert to bytes
    flat_bytes = arr.flatten().tobytes()

    # Create a hash object and update it with the bytes
    hash_obj = hashlib.sha256()
    hash_obj.update(flat_bytes)

    # Return the hexadecimal representation of the hash and the shape of the array
    return f"{hash_obj.hexdigest()}_{'_'.join(map(str, arr_shape))}"


@dataclass
class STEpisodeGeneratorConfig(BaseExplorerSensorConfig):
    type: str = STEpisodeGenerator.__name__
    output_dir: str = "data/spatiotemporal_episodes/"
    ang_vel: float = 30.0  # degrees per second
    forward_step_size: float = 0.5  # meters
    lin_vel: float = 0.5  # meters per second
    turn_angle: float = 30.0  # degrees
    visibility_dist: float = 4.5  # in meters
    area_thresh: float = 5.0  # square meters
    minimize_time: bool = True
    num_episodes: int = 1000


cs = ConfigStore.instance()
cs.store(
    package="habitat.task.lab_sensors.st_exploration_episode_generator",
    group="habitat/task/lab_sensors",
    name="st_exploration_episode_generator",
    node=STEpisodeGeneratorConfig,
)
