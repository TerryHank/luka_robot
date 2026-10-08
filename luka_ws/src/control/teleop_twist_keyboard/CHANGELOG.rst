^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Changelog for package teleop_twist_keyboard
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

2.4.1 (2025-09-26)
------------------
* replace tests_require with extra_require (`#38 <https://github.com/ros2/teleop_twist_keyboard/issues/38>`_)
  * replace tests_require with extra_require
  Co-authored-by: Chris Lalancette <clalancette@gmail.com>
* Set all parameters as read-only. (`#40 <https://github.com/ros2/teleop_twist_keyboard/issues/40>`_)
  * Reject parameter updates.
  While there are a number of parameters here that can be
  set at startup, none of them can actually be configured
  at runtime successfully.  Set them to read-only.
* Add speed&turn parameters (`#34 <https://github.com/ros2/teleop_twist_keyboard/issues/34>`_)
  * Add speed&turn parameters
  Co-authored-by: G.A. vd. Hoorn <g.a.vanderhoorn@tudelft.nl>
* Contributors: Arend-Jan van Hilten, Chris Lalancette, Plumezz

2.4.0 (2024-03-08)
------------------
* Fixes for flake8. (`#29 <https://github.com/ros2/teleop_twist_keyboard/issues/29>`_)
* Show command to change topic name on readme (`#27 <https://github.com/ros2/teleop_twist_keyboard/issues/27>`_)
* Remove url for ros1 on package.xml (`#28 <https://github.com/ros2/teleop_twist_keyboard/issues/28>`_)
* Added TwistStamped option (`#26 <https://github.com/ros2/teleop_twist_keyboard/issues/26>`_)
* Switch to underscores for setup.cfg. (`#25 <https://github.com/ros2/teleop_twist_keyboard/issues/25>`_)
* Contributors: Asuki Kono, Chris Lalancette, agyoungs

2.3.2 (2020-05-12)
------------------
* Add Windows support to teleop_twist_keyboard. (`#24 <https://github.com/ros2/teleop_twist_keyboard/issues/24>`_)
* Contributors: Chris Lalancette

2.3.1 (2019-10-03)
------------------
* Stop using deprecated APIs. (`#22 <https://github.com/ros2/teleop_twist_keyboard/issues/22>`_)
* Contributors: Chris Lalancette

2.3.0 (2019-04-19)
------------------
* changing QoS to default (`#18 <https://github.com/ros2/teleop_twist_keyboard/issues/18>`_)
* Contributors: thorstink

2.1.1 (2018-06-26)
------------------

2.1.0 (2018-06-26)
------------------
* set zip_safe to avoid warning during installation (`#14 <https://github.com/ros2/teleop_twist_keyboard/issues/14>`_)
* Update the maintainer to me. (`#13 <https://github.com/ros2/teleop_twist_keyboard/issues/13>`_)
* fix data files install path (`#12 <https://github.com/ros2/teleop_twist_keyboard/issues/12>`_)
* remove test_suite, add pytest as test_requires (`#11 <https://github.com/ros2/teleop_twist_keyboard/issues/11>`_)
* use ros2 run to launch whichever the installation used (`#8 <https://github.com/ros2/teleop_twist_keyboard/issues/8>`_)
* Fix teleop_twist_keyboard to have a setup.cfg. (`#9 <https://github.com/ros2/teleop_twist_keyboard/issues/9>`_)
* Make sure to add teleop_twist_keyboard to ament index. (`#6 <https://github.com/ros2/teleop_twist_keyboard/issues/6>`_)
* use OSI website as reference for license (`#2 <https://github.com/ros2/teleop_twist_keyboard/issues/2>`_)
* ROS 2 port (`#1 <https://github.com/ros2/teleop_twist_keyboard/issues/1>`_)
* Contributors: Adam Allevato, Austin, Chris Lalancette, Dirk Thomas, Mikael Arguedas

0.6.1 (2018-05-02)
------------------
* import print from future
* Print python3 compatible
* correct Exception handling
* Merge pull request `#7 <https://github.com/ros-teleop/teleop_twist_keyboard/issues/7>`_ from lucasw/speed_params
  set linear and turn speed via rosparams
* Using tabs instead of spaces to match rest of file
* set linear and turn speed via rosparams
* Contributors: Austin, Lucas Walter, Matthijs van der Burgh

0.6.0 (2016-03-21)
------------------
* Better instruction formatting
* support holonomic base, send commmand with keyboard down
* Fixing queue_size warning
* Create README.md
* Update the description string in package.xml
* Contributors: Austin, Kei Okada, LiohAu, Mike Purvis, kk6axq, trainman419

0.5.0 (2014-02-11)
------------------
* Initial import from brown_remotelab
* Convert to catkin
