import setuptools

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setuptools.setup(
    name="QMDataSDK",
    version="0.0.1a1.dev1",
    author="Jun Wang",
    author_email="jstzwj@aliyun.com",
    description="A Python SDK for QMData",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/quantmew/qmdatasdk",
    project_urls={
        "Bug Tracker": "https://github.com/quantmew/qmdatasdk/issues",
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
    packages=['qmdatasdk'],
    python_requires='>=3.9',
    install_requires=[
        'numpy>=1.19.2',
        'pandas>=1.3.0',
        'SQLAlchemy>=2.0.41',
        'pymysql>=0.7.6',
    ]
)