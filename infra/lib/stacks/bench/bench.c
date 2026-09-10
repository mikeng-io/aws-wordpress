/* E3 microbenchmark: per-syscall latency for stat/open+read/create/unlink,
 * against whatever directory is named on argv[1].
 *
 * Not fio, deliberately - fio's default patterns are throughput-oriented, and
 * the WordPress storm E0 measured is small-file METADATA ops, not throughput.
 * This mimics that shape: a nested directory tree, files in the 2-50KB range
 * (matching E0's plugin-file profile), timed individually via
 * clock_gettime(CLOCK_MONOTONIC) around each syscall - not around a batch, since
 * a batch average would hide exactly the tail behaviour this experiment exists to
 * find. Output is one CSV line per op: "op,ns" - percentile analysis happens
 * downstream in Python, matching E0's raw-output-then-analyze pattern.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/stat.h>
#include <errno.h>

#define DIRS 20
#define FILES_PER_DIR 50
#define MAX_PATH 512

static long ns_between(struct timespec *a, struct timespec *b) {
    return (b->tv_sec - a->tv_sec) * 1000000000L + (b->tv_nsec - a->tv_nsec);
}

/* Deterministic "random" size in [2048, 51200] bytes - a fixed seed so the same
 * tree shape is built every run, on every mount, making local-vs-EFS a fair
 * comparison of the same workload rather than different workloads that happen to
 * average out similarly. */
static size_t file_size(int dir_i, int file_i) {
    unsigned h = (unsigned)(dir_i * 9973 + file_i * 7919);
    return 2048 + (h % (51200 - 2048));
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "usage: bench <target-dir>\n");
        return 64;
    }
    const char *root = argv[1];
    struct timespec t0, t1;
    char path[MAX_PATH];
    char *buf = malloc(51200);
    memset(buf, 'e', 51200);

    /* --- build the tree, timing each create --- */
    for (int d = 0; d < DIRS; d++) {
        snprintf(path, sizeof(path), "%s/plugin-%03d/includes", root, d);
        /* mkdir -p by hand: two levels, ignore EEXIST */
        char parent[MAX_PATH];
        snprintf(parent, sizeof(parent), "%s/plugin-%03d", root, d);
        mkdir(parent, 0755);
        mkdir(path, 0755);

        for (int f = 0; f < FILES_PER_DIR; f++) {
            snprintf(path, sizeof(path), "%s/plugin-%03d/includes/class-%03d.php", root, d, f);
            size_t sz = file_size(d, f);

            clock_gettime(CLOCK_MONOTONIC, &t0);
            int fd = open(path, O_CREAT | O_WRONLY | O_TRUNC, 0644);
            if (fd < 0) { fprintf(stderr, "create failed: %s: %s\n", path, strerror(errno)); return 1; }
            ssize_t written = write(fd, buf, sz);
            (void)written;
            close(fd);
            clock_gettime(CLOCK_MONOTONIC, &t1);
            printf("create,%ld\n", ns_between(&t0, &t1));
        }
    }

    /* --- stat pass --- */
    for (int d = 0; d < DIRS; d++) {
        for (int f = 0; f < FILES_PER_DIR; f++) {
            snprintf(path, sizeof(path), "%s/plugin-%03d/includes/class-%03d.php", root, d, f);
            struct stat st;
            clock_gettime(CLOCK_MONOTONIC, &t0);
            int rc = stat(path, &st);
            clock_gettime(CLOCK_MONOTONIC, &t1);
            if (rc != 0) { fprintf(stderr, "stat failed: %s\n", path); return 1; }
            printf("stat,%ld\n", ns_between(&t0, &t1));
        }
    }

    /* --- open+read+close pass, the PHP include primitive --- */
    for (int d = 0; d < DIRS; d++) {
        for (int f = 0; f < FILES_PER_DIR; f++) {
            snprintf(path, sizeof(path), "%s/plugin-%03d/includes/class-%03d.php", root, d, f);
            clock_gettime(CLOCK_MONOTONIC, &t0);
            int fd = open(path, O_RDONLY);
            if (fd < 0) { fprintf(stderr, "open failed: %s\n", path); return 1; }
            ssize_t r;
            do { r = read(fd, buf, 51200); } while (r > 0);
            close(fd);
            clock_gettime(CLOCK_MONOTONIC, &t1);
            printf("open_read,%ld\n", ns_between(&t0, &t1));
        }
    }

    /* --- ENOENT pass - a third of E0's real-world floor was failed lookups --- */
    for (int d = 0; d < DIRS; d++) {
        snprintf(path, sizeof(path), "%s/plugin-%03d/includes/does-not-exist.php", root, d);
        struct stat st;
        clock_gettime(CLOCK_MONOTONIC, &t0);
        stat(path, &st); /* expected to fail; timing the failure path itself */
        clock_gettime(CLOCK_MONOTONIC, &t1);
        printf("stat_enoent,%ld\n", ns_between(&t0, &t1));
    }

    /* --- unlink pass --- */
    for (int d = 0; d < DIRS; d++) {
        for (int f = 0; f < FILES_PER_DIR; f++) {
            snprintf(path, sizeof(path), "%s/plugin-%03d/includes/class-%03d.php", root, d, f);
            clock_gettime(CLOCK_MONOTONIC, &t0);
            int rc = unlink(path);
            clock_gettime(CLOCK_MONOTONIC, &t1);
            if (rc != 0) { fprintf(stderr, "unlink failed: %s\n", path); return 1; }
            printf("unlink,%ld\n", ns_between(&t0, &t1));
        }
    }

    free(buf);
    return 0;
}
