from setuptools import setup, find_packages

with open("requirements.txt") as f:
    requirements = f.read().splitlines()

setup(
   name='traffic-translator',
   version='1.0.0',
   description='Multi-protocol traffic signal controller translator',
   author='Traffic Translator Team',
   author_email='traffic@example.com',
   packages=find_packages(),
   install_requires=requirements,
   entry_points={
       'console_scripts': [
           'traffic-translator=traffic_translator.main:main',
       ],
   },
   classifiers=[
       'Development Status :: 4 - Beta',
       'Intended Audience :: Developers',
       'License :: OSI Approved :: MIT License',
       'Programming Language :: Python :: 3',
       'Programming Language :: Python :: 3.8',
       'Programming Language :: Python :: 3.9',
       'Programming Language :: Python :: 3.10',
       'Programming Language :: Python :: 3.11',
   ],
   python_requires='>=3.8',
)