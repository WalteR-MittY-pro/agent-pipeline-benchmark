# 示例 Dockerfile 
FROM python:3.13

# 安装 C++ 编译工具链和 Git
RUN apt-get update && apt-get install -y \
    git build-essential cmake ninja-build vim \
    libeigen3-dev \
    && rm -rf /var/lib/apt/lists/*

# 设置工作目录
WORKDIR /workspace

# 克隆 nanobind 仓库到特定 commit（PR 发生前的基础 commit）
# 假设 base commit 是 a1b2c3d4
RUN git clone --recursive https://github.com/wjakob/nanobind.git .
    # && git checkout a1b2c3d4

# 安装依赖
RUN pip install pytest scikit-build-core
RUN pip install -e .

RUN mkdir -p build && cd build && cmake .. && make

# 预留给后续打 Patch 和跑测试的入口
CMD ["bash"]