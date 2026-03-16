from setuptools import setup, find_packages

setup(
    name='afl_stats_search',
    version='0.2.0',
    packages=find_packages(),
    install_requires=[
        'fastapi==0.111.0',
        'uvicorn==0.30.1',
        'python-dotenv==1.0.1',
        'jinja2==3.1.3',
        'httpx==0.27.0',
        'beautifulsoup4==4.13.4',
    ],
    entry_points={
        'console_scripts': [
            'afl-stats-search=main:main',
        ],
    },
)
