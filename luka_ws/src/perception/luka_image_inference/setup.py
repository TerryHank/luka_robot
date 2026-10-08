from setuptools import setup,find_packages
setup(name='luka_image_inference',version='0.1.0',packages=find_packages(),
 data_files=[('share/ament_index/resource_index/packages',['resource/luka_image_inference']),
             ('share/luka_image_inference',['package.xml'])],
 entry_points={'console_scripts':['image_inference = luka_image_inference.api:main',
                                 'dynamic_mask = luka_image_inference.mask_stream:main']})
