#include <libobsensor/ObSensor.hpp>
#include <iostream>
int main() {
  try {
    ob::Context context;
    context.setLoggerSeverity(OB_LOG_SEVERITY_ERROR);
    auto devices = context.queryDeviceList();
    std::cout << "devices=" << devices->deviceCount() << std::endl;
    for (uint32_t i = 0; i < devices->deviceCount(); ++i) {
      auto device = devices->getDevice(i);
      auto info = device->getDeviceInfo();
      std::cout << "name=" << info->name() << " firmware=" << info->firmwareVersion()
                << " serial=" << info->serialNumber() << " pid=" << info->pid() << std::endl;
    }
  } catch (ob::Error &error) {
    std::cerr << error.getMessage() << std::endl;
    return 1;
  }
}
