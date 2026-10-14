/* E2 throughput probe: sequential write and read bandwidth against argv[1].
 *
 * bench.c measures what WordPress does most - per-file metadata ops on small files.
 * Prediction 1 says that ranking differs from a throughput ranking, which needs a
 * throughput ranking to exist. This is it, and nothing more: the method is fixed in
 * experiments/E2-storage-matrix/README.md ("Prediction 1: the throughput
 * measurement") and this file implements that section, not a variant of it.
 *
 *   1. STREAMS threads each write one FILE_BYTES file in CHUNK writes, fsync, close.
 *   2. Two read phases, 1-stream and STREAMS-stream, in the order given on argv[2].
 *   3. Before each read phase every file is dropped from the client page cache with
 *      POSIX_FADV_DONTNEED, and residency is then MEASURED with mincore(2). Eviction
 *      is verified rather than assumed, because a read served from RAM looks exactly
 *      like a fast tier once it is a number in a CSV.
 *
 * Output, one line per phase:
 *   phase,streams,bytes,ns,resident_pct
 * resident_pct is the page-cache residency measured immediately before the phase
 * (-1 for the write phase, where it does not apply). Grading reads it; this program
 * only reports it. Exit status is non-zero only when the probe itself could not run.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define STREAMS 4
#define CHUNK (1L << 20)
#define MAX_PATH 512

static long long file_bytes = 1LL << 30; /* 1 GiB; TPUT_FILE_MIB overrides for local tests */
static char paths[STREAMS][MAX_PATH];

static long long now_ns(void) {
    struct timespec t;
    clock_gettime(CLOCK_MONOTONIC, &t);
    return (long long)t.tv_sec * 1000000000LL + t.tv_nsec;
}

static void die(const char *what, const char *path) {
    fprintf(stderr, "tput: %s %s: %s\n", what, path, strerror(errno));
    exit(1);
}

/* --- a start barrier, so wall time is measured from the moment every thread can
 *     go rather than from thread creation, which would add scheduler noise to the
 *     short phases --- */
static pthread_barrier_t start_line;

struct job { int first, last; int write; };

static void *worker(void *arg) {
    struct job *j = arg;
    char *buf = aligned_alloc(4096, CHUNK);
    if (!buf) { fprintf(stderr, "tput: out of memory\n"); exit(1); }
    memset(buf, 't', CHUNK);
    pthread_barrier_wait(&start_line);
    for (int f = j->first; f <= j->last; f++) {
        if (j->write) {
            int fd = open(paths[f], O_CREAT | O_WRONLY | O_TRUNC, 0644);
            if (fd < 0) die("open for write", paths[f]);
            for (long long done = 0; done < file_bytes; done += CHUNK) {
                ssize_t w = write(fd, buf, CHUNK);
                if (w < 0) die("write", paths[f]);
                if (w != CHUNK) {
                    /* errno is not set on a short write; usually the tier is full. */
                    fprintf(stderr, "tput: short write %s: %zd of %ld bytes\n", paths[f], w, CHUNK);
                    exit(1);
                }
            }
            /* fsync is inside the timed region: a write that has not reached the
             * tier has not been measured against the tier. */
            if (fsync(fd) != 0) die("fsync", paths[f]);
            close(fd);
        } else {
            int fd = open(paths[f], O_RDONLY);
            if (fd < 0) die("open for read", paths[f]);
            long long got = 0;
            ssize_t r;
            while ((r = read(fd, buf, CHUNK)) > 0) got += r;
            if (r < 0) die("read", paths[f]);
            if (got != file_bytes) {
                fprintf(stderr, "tput: %s read %lld of %lld bytes\n", paths[f], got, file_bytes);
                exit(1);
            }
            close(fd);
        }
    }
    free(buf);
    return NULL;
}

/* Run one phase with `streams` threads over all files; returns wall ns. */
static long long run_phase(int streams, int write) {
    pthread_t t[STREAMS];
    struct job jobs[STREAMS];
    pthread_barrier_init(&start_line, NULL, (unsigned)streams + 1);
    for (int i = 0; i < streams; i++) {
        if (streams == 1) { jobs[i].first = 0; jobs[i].last = STREAMS - 1; }
        else { jobs[i].first = i; jobs[i].last = i; }
        jobs[i].write = write;
        pthread_create(&t[i], NULL, worker, &jobs[i]);
    }
    pthread_barrier_wait(&start_line);
    long long t0 = now_ns();
    for (int i = 0; i < streams; i++) pthread_join(t[i], NULL);
    long long t1 = now_ns();
    pthread_barrier_destroy(&start_line);
    return t1 - t0;
}

/* Drop every file from the client page cache, then measure what is still resident.
 * Returns the resident percentage across all files. */
static double evict_and_measure(void) {
    long page = sysconf(_SC_PAGESIZE);
    long long resident = 0, total = 0;
    for (int f = 0; f < STREAMS; f++) {
        int fd = open(paths[f], O_RDONLY);
        if (fd < 0) die("open for evict", paths[f]);
        /* TPUT_SKIP_EVICT exists only to prove the residency check can fire: with
         * eviction skipped, a just-written file must read back as resident. A guard
         * that has never been seen to trip is not known to work. Never set in a task
         * definition. */
        if (!getenv("TPUT_SKIP_EVICT")) {
            int rc = posix_fadvise(fd, 0, 0, POSIX_FADV_DONTNEED);
            if (rc != 0) { errno = rc; die("posix_fadvise", paths[f]); }
        }
        void *map = mmap(NULL, (size_t)file_bytes, PROT_READ, MAP_SHARED, fd, 0);
        if (map == MAP_FAILED) die("mmap", paths[f]);
        size_t pages = (size_t)((file_bytes + page - 1) / page);
        unsigned char *vec = malloc(pages);
        if (!vec) { fprintf(stderr, "tput: out of memory\n"); exit(1); }
        if (mincore(map, (size_t)file_bytes, vec) != 0) die("mincore", paths[f]);
        for (size_t p = 0; p < pages; p++) resident += vec[p] & 1;
        total += (long long)pages;
        free(vec);
        munmap(map, (size_t)file_bytes);
        close(fd);
    }
    return total ? 100.0 * (double)resident / (double)total : 100.0;
}

int main(int argc, char **argv) {
    if (argc < 3) {
        fprintf(stderr, "usage: tput <target-dir> <read-order: 1,4 | 4,1>\n");
        return 64;
    }
    const char *root = argv[1];
    const char *order = argv[2];
    if (strcmp(order, "1,4") != 0 && strcmp(order, "4,1") != 0) {
        fprintf(stderr, "tput: read order must be 1,4 or 4,1, got %s\n", order);
        return 64;
    }
    const char *mib = getenv("TPUT_FILE_MIB");
    if (mib && *mib) file_bytes = atoll(mib) * CHUNK;
    if (file_bytes < CHUNK) { fprintf(stderr, "tput: file size below 1 MiB\n"); return 64; }

    if (mkdir(root, 0755) != 0 && errno != EEXIST) die("mkdir", root);
    for (int f = 0; f < STREAMS; f++)
        snprintf(paths[f], MAX_PATH, "%s/tput-%d.bin", root, f);

    long long bytes = file_bytes * STREAMS;
    long long ns = run_phase(STREAMS, 1);
    printf("write,%d,%lld,%lld,-1\n", STREAMS, bytes, ns);

    for (int k = 0; k < 2; k++) {
        int streams = (order[k * 2] == '1') ? 1 : STREAMS;
        double res = evict_and_measure();
        ns = run_phase(streams, 0);
        printf("read,%d,%lld,%lld,%.3f\n", streams, bytes, ns, res);
        fflush(stdout);
    }

    for (int f = 0; f < STREAMS; f++) unlink(paths[f]);
    rmdir(root);
    return 0;
}
