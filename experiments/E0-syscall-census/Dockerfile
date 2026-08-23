# E0 apparatus image: WordPress + php-fpm, plus the tools needed to trace it.
#
# The plugin set is deliberately heavy and deliberately pinned — the whole point is
# to measure a realistic legacy install, and an unpinned set makes results
# irreproducible.  Pin versions before the first real run.
FROM wordpress:php8.3-fpm

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        strace \
        libfcgi-bin \
        less \
        jq \
        unzip; \
    rm -rf /var/lib/apt/lists/*

# Exactly one worker, so a trace is attributable to a single request.
RUN { \
      echo '[www]'; \
      echo 'pm = static'; \
      echo 'pm.max_children = 1'; \
      echo 'catch_workers_output = yes'; \
    } > /usr/local/etc/php-fpm.d/zz-e0.conf

# TODO: install and pin the heavy plugin set (WooCommerce + ~25 popular plugins)
#       and seed a deterministic catalog.  Until then E0 measures vanilla WP, which
#       understates the effect - see README prediction.

COPY entrypoint-e0.sh /usr/local/bin/entrypoint-e0.sh
RUN chmod +x /usr/local/bin/entrypoint-e0.sh
ENTRYPOINT ["/usr/local/bin/entrypoint-e0.sh"]
CMD ["php-fpm"]
