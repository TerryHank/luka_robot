from .ros_topic_backend import RosTopicBackend


class HobotLlamaCppBackend(RosTopicBackend):
    def __init__(self, node, timeout_sec=12.0,
                 prompt_topic="/luka/llm/llamacpp/prompt",
                 result_topic="/luka/llm/llamacpp/final"):
        super().__init__(
            node, "hobot_llamacpp", prompt_topic, result_topic, timeout_sec)
