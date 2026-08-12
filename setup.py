from setuptools import setup, find_packages

with open('README.md', 'r', encoding='utf-8') as f:
    long_description = f.read()

setup(
    name='zikra',
    version='1.0.14',
    description='Persistent memory for AI agents — FastAPI + SQLite + sqlite-vec, with optional PostgreSQL',
    long_description=long_description,
    long_description_content_type='text/markdown',
    author='Zikra Contributors',
    license='MIT',
    packages=find_packages(),
    python_requires='>=3.10',
    install_requires=[
        'fastapi==0.140.7',
        'uvicorn==0.51.0',
        'httpx==0.28.1',
        'sqlite-vec==0.1.9',
        'aiosqlite==0.22.1',
        'python-dotenv==1.2.2',
        'mcp[cli]==1.28.1',
        'starlette==1.3.1',
    ],
    extras_require={
        'postgres': ['asyncpg==0.31.0'],
        'full':     ['asyncpg==0.31.0'],
    },
    entry_points={
        'console_scripts': [
            'zikra = zikra.__main__:main',
        ],
    },
    classifiers=[
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
)
