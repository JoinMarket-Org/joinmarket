#
# Quick and easy joinmarket
#
# docker build -t "bwstitt/joinmarket:latest" .
#
# Copying of the code is delayed as long as possible so that rebuilding the container while developing is faster
# This also means some of the install steps aren't in the most obvious order and the virtualenv is outside the code
#

FROM bwstitt/python-jessie:python2

# Install packages for joinmarket
RUN docker-apt-install \
    gcc \
    libsodium13 \
    python-dev

# i needed these when compiling myself, but new versions of pip with wheels save us
    #libatlas-dev \
    #libblas-dev \
    #libfreetype6-dev \
    #libpng12-dev \
    #libsodium-dev \
    #pkg-config \
    #python-dev \

# install deps that don't depend on the code as the user and fix /pyenv/local/lib/python2.7/site-packages/matplotlib/font_manager.py:273: UserWarning: Matplotlib is building the font cache using fc-list. This may take a moment.
# TODO: double check that this actually builds the font caches
RUN chroot --userspec=abc / pip install matplotlib==2.0.0 \
 && chroot --userspec=abc / python -c \
    "from matplotlib.font_manager import FontManager; print(FontManager())"

# copy requirements before code. this will make the image builds faster when code changes but requirements don't
COPY requirements.txt /src/
RUN chroot --userspec=abc / pip install -r /src/requirements.txt

# install the code
# todo: i wish copy would keep the user...
COPY . /src/
WORKDIR /src
RUN chown -R abc:abc .

# setup data volumes for logs and wallets
# todo: handle the blacklist and commitments
VOLUME /src/logs /src/wallets

USER abc
ENV MPLBACKEND=agg
ENTRYPOINT ["python", "/src/docker/entrypoint.py"]
CMD ["ob_watcher", "-H", "0.0.0.0"]

EXPOSE 62601
