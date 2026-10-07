"""Vehicle adapter; only this boundary imports the motor implementation."""
def create_driver():
 from ddsm_car_control.zdt_mecanum_rs485_bridge import ZDTMecanumRS485Bridge
 return ZDTMecanumRS485Bridge()
