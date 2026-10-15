/* E5 instrument: per-syscall latency on a tree this client did NOT just create.
 *
 * bench.c (E2/E3) creates its files and stats them seconds later, so on NFS it
 * measured the client attribute cache, not the server. agebench never creates the
 * tree: the host seeds it through a separate mount that is unmounted before
 * measurement, so every mount agebench reads meets the files as a client that has
 * never seen them. bench.c is deliberately left untouched - E2 and E3's instrument
 * must stay byte-identical - and the tree shape and file_size() below are copied
 * from it, so the two are the same workload.
 *
 * Two modes:
 *
 *   agebench pass <dir> <op> <cohort>
 *       One timed pass over the tree in fixed order. op is stat | enoent | open_read.
 *       Writes one raw line per op: "cohort,op,seq,ns". Exits non-zero if any
 *       stat/open of a file that should exist fails (a missing seed must not read
 *       as a fast ENOENT).
 *
 *   agebench serve <dir> <interval_s> <start_epoch_s> <warmup_s> <measure_s>
 *                  <guard_s> <raw_every> <cohort>
 *       A web tier after a deploy. First "compile": open_read every file once
 *       (opcache's first request; on FSx OpenZFS, when read delegations are
 *       granted). Then requests at FIXED-RATE deadlines start+k*interval
 *       (clock_nanosleep TIMER_ABSTIME on CLOCK_REALTIME, so every process in the
 *       task shares one timeline and the external counter snapshots line up). One
 *       request stats all 1,000 files and all 1,000 missing names.
 *       - A deadline already passed is SKIPPED, not caught up: a burst of catch-up
 *         requests would revalidate nothing new and inflate the hit count.
 *       - No request starts within guard_s of the warm-up boundary or of the end,
 *         so a request never straddles the moment the counters are read.
 *       - Per request, per op: a log-binned histogram (20 bins per decade from
 *         100 ns; exact counts), the summed ns, and the request's lateness.
 *       - Every raw_every-th request also writes every op raw.
 *       Output lines:
 *         req,<k>,<phase>,<lateness_ns>,<dur_ns>,<op>,<n>,<sum_ns>,<bin:count;...>
 *         raw,<k>,<op>,<seq>,<ns>
 *         skip,<k>,<phase>
 *       phase is warmup | measure.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <time.h>
#include <unistd.h>

#define DIRS 20
#define FILES_PER_DIR 50
#define N (DIRS * FILES_PER_DIR)
#define MAX_PATH 512
#define BINS 140 /* 20 per decade, 100 ns .. 1 s */

static char paths[N][MAX_PATH];
static char missing[N][MAX_PATH];
static char buf[51200];

static long ns_between(const struct timespec *a, const struct timespec *b) {
    return (b->tv_sec - a->tv_sec) * 1000000000L + (b->tv_nsec - a->tv_nsec);
}

static long now_realtime_ns(void) {
    struct timespec t;
    clock_gettime(CLOCK_REALTIME, &t);
    return t.tv_sec * 1000000000L + t.tv_nsec;
}

/* Bin 0 is < 100 ns; bin b >= 1 holds [100 * 10^((b-1)/20), 100 * 10^(b/20)) ns. */
static int bin_of(long ns) {
    if (ns < 100) return 0;
    int b = 1 + (int)floor(20.0 * log10((double)ns / 100.0));
    return b >= BINS ? BINS - 1 : b;
}

static void build_paths(const char *root) {
    for (int d = 0; d < DIRS; d++)
        for (int f = 0; f < FILES_PER_DIR; f++) {
            int i = d * FILES_PER_DIR + f;
            snprintf(paths[i], MAX_PATH, "%s/plugin-%03d/includes/class-%03d.php", root, d, f);
            snprintf(missing[i], MAX_PATH, "%s/plugin-%03d/includes/missing-%03d.php", root, d, f);
        }
}

/* One timed op. Returns ns, or -1 on an unexpected failure. */
static long timed_stat(const char *p, int expect_exist) {
    struct timespec t0, t1;
    struct stat st;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    int rc = stat(p, &st);
    clock_gettime(CLOCK_MONOTONIC, &t1);
    if (expect_exist && rc != 0) { fprintf(stderr, "stat failed: %s: %s\n", p, strerror(errno)); return -1; }
    if (!expect_exist && rc == 0) { fprintf(stderr, "expected ENOENT, found: %s\n", p); return -1; }
    if (!expect_exist && errno != ENOENT) { fprintf(stderr, "expected ENOENT: %s: %s\n", p, strerror(errno)); return -1; }
    return ns_between(&t0, &t1);
}

static long timed_open_read(const char *p) {
    struct timespec t0, t1;
    clock_gettime(CLOCK_MONOTONIC, &t0);
    int fd = open(p, O_RDONLY);
    if (fd < 0) { fprintf(stderr, "open failed: %s: %s\n", p, strerror(errno)); return -1; }
    ssize_t r;
    do { r = read(fd, buf, sizeof buf); } while (r > 0);
    close(fd);
    clock_gettime(CLOCK_MONOTONIC, &t1);
    if (r < 0) { fprintf(stderr, "read failed: %s\n", p); return -1; }
    return ns_between(&t0, &t1);
}

static int do_pass(const char *op, const char *cohort) {
    for (int i = 0; i < N; i++) {
        long ns;
        if (strcmp(op, "stat") == 0) ns = timed_stat(paths[i], 1);
        else if (strcmp(op, "enoent") == 0) ns = timed_stat(missing[i], 0);
        else if (strcmp(op, "open_read") == 0) ns = timed_open_read(paths[i]);
        else { fprintf(stderr, "unknown op %s\n", op); return 64; }
        if (ns < 0) return 1;
        printf("%s,%s,%d,%ld\n", cohort, op, i, ns);
    }
    return 0;
}

struct acc { long n, sum; long bins[BINS]; };

static void acc_add(struct acc *a, long ns) { a->n++; a->sum += ns; a->bins[bin_of(ns)]++; }

static void acc_print(long k, const char *phase, long late, long dur, const char *op, const struct acc *a) {
    printf("req,%ld,%s,%ld,%ld,%s,%ld,%ld,", k, phase, late, dur, op, a->n, a->sum);
    int first = 1;
    for (int b = 0; b < BINS; b++)
        if (a->bins[b]) { printf("%s%d:%ld", first ? "" : ";", b, a->bins[b]); first = 0; }
    printf("\n");
}

static int do_serve(double interval, double start_epoch, double warmup, double measure,
                    double guard, long raw_every, const char *cohort) {
    /* compile: open every file once, untimed as a cohort but recorded raw */
    for (int i = 0; i < N; i++) {
        long ns = timed_open_read(paths[i]);
        if (ns < 0) return 1;
        printf("raw,-1,compile,%d,%ld\n", i, ns);
    }
    fflush(stdout);
    long start_ns = (long)(start_epoch * 1e9);
    long iv_ns = (long)(interval * 1e9);
    long warm_ns = start_ns + (long)(warmup * 1e9);
    long end_ns = warm_ns + (long)(measure * 1e9);
    long guard_ns = (long)(guard * 1e9);
    if (now_realtime_ns() > start_ns) {
        fprintf(stderr, "compile finished after the shared start time - refusing a skewed timeline\n");
        return 2;
    }
    for (long k = 0;; k++) {
        long deadline = start_ns + k * iv_ns;
        if (deadline >= end_ns) break;
        const char *phase = deadline < warm_ns ? "warmup" : "measure";
        int in_guard = (deadline >= warm_ns - guard_ns && deadline < warm_ns + guard_ns) ||
                       deadline >= end_ns - guard_ns;
        long now = now_realtime_ns();
        if (in_guard || now > deadline + iv_ns / 2 + 1) {
            /* passed by more than half an interval, or inside a guard: skip */
            if (!in_guard) printf("skip,%ld,%s\n", k, phase);
            continue;
        }
        struct timespec dl = { deadline / 1000000000L, deadline % 1000000000L };
        while (clock_nanosleep(CLOCK_REALTIME, TIMER_ABSTIME, &dl, NULL) == EINTR) {}
        long t_start = now_realtime_ns();
        int raw = raw_every > 0 && k % raw_every == 0;
        struct acc st = {0}, en = {0};
        for (int i = 0; i < N; i++) {
            long ns = timed_stat(paths[i], 1);
            if (ns < 0) return 1;
            acc_add(&st, ns);
            if (raw) printf("raw,%ld,stat,%d,%ld\n", k, i, ns);
        }
        for (int i = 0; i < N; i++) {
            long ns = timed_stat(missing[i], 0);
            if (ns < 0) return 1;
            acc_add(&en, ns);
            if (raw) printf("raw,%ld,enoent,%d,%ld\n", k, i, ns);
        }
        long dur = now_realtime_ns() - t_start;
        acc_print(k, phase, t_start - deadline, dur, "stat", &st);
        acc_print(k, phase, t_start - deadline, dur, "enoent", &en);
        /* A request still running at a counter snapshot would split its RPCs across
         * two windows. The guard should prevent it; if it did not, say so. */
        if ((t_start < warm_ns && t_start + dur > warm_ns - guard_ns / 2) ||
            t_start + dur > end_ns - guard_ns / 2)
            printf("overrun,%ld,%s\n", k, phase);
        fflush(stdout);
    }
    return 0;
}

int main(int argc, char **argv) {
    if (argc >= 5 && strcmp(argv[1], "pass") == 0) {
        build_paths(argv[2]);
        return do_pass(argv[3], argv[4]);
    }
    if (argc >= 10 && strcmp(argv[1], "serve") == 0) {
        build_paths(argv[2]);
        return do_serve(atof(argv[3]), atof(argv[4]), atof(argv[5]), atof(argv[6]),
                        atof(argv[7]), atol(argv[8]), argv[9]);
    }
    fprintf(stderr,
        "usage: agebench pass <dir> stat|enoent|open_read <cohort>\n"
        "       agebench serve <dir> <interval_s> <start_epoch_s> <warmup_s> <measure_s> <guard_s> <raw_every> <cohort>\n");
    return 64;
}
