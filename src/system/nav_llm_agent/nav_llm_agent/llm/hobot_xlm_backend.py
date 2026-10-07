from .ros_topic_backend import RosTopicBackend


class HobotXlmBackend(RosTopicBackend):
    def __init__(self, node, timeout_sec=12.0,
                 prompt_topic="/luka/llm/xlm/prompt",
                 result_topic="/luka/llm/xlm/final"):
        super().__init__(
            node, "hobot_xlm", prompt_topic, result_topic, timeout_sec)
