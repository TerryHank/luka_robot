// Copyright 2026 TerryHank
// Licensed under the Apache License, Version 2.0.
#include "tros_person_following/person_following_node.h"

#include <csignal>
#include <chrono>
#include <thread>

namespace {
volatile std::sig_atomic_t stopping = 0;
void stopSignal(int) { stopping = 1; }
}

int main(int argc, char ** argv)
{
  rclcpp::init(argc, argv, rclcpp::InitOptions(), rclcpp::SignalHandlerOptions::None);
  std::signal(SIGINT, stopSignal);
  std::signal(SIGTERM, stopSignal);
  auto node = std::make_shared<tros_person_following::PersonFollowingNode>();
  rclcpp::executors::SingleThreadedExecutor executor;
  executor.add_node(node);
  while (rclcpp::ok() && !stopping) {
    executor.spin_some();
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }
  if (rclcpp::ok()) {
    node->prepareShutdown();
    // Keep the client alive to cancel a late accepted goal by its own UUID.
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(3);
    do {
      executor.spin_some();
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
    } while (std::chrono::steady_clock::now() < deadline && rclcpp::ok());
    if (node->pendingNavRequests()) {
      RCLCPP_ERROR(node->get_logger(), "Shutdown timed out waiting for goal response; verify Nav2 stopped");
    }
  }
  executor.remove_node(node);
  node.reset();
  rclcpp::shutdown();
  return 0;
}
