#!/usr/bin/perl
use strict;
use warnings;
use utf8;
use JSON::PP qw(encode_json decode_json);
use Encode qw(decode FB_DEFAULT);
use IO::Select;
use POSIX qw(:sys_wait_h);
use Time::HiRes qw(time);
use Errno qw(EINTR);

# Native OmniShell v1 provider. Core macOS Perl modules only; no sudo, shell,
# keys, configuration files, or WireGuard command-line installation needed.
my $child = 0;
sub stop_child {
    if ($child) {
        kill 'KILL', $child;
        while (waitpid($child, 0) < 0 && $! == EINTR) {}
        $child = 0;
    }
}
$SIG{TERM} = sub { stop_child(); exit 0 };
$SIG{INT} = sub { stop_child(); exit 0 };
END { stop_child() }

sub emit { print encode_json($_[0]), "\n" or exit 0 }

sub command {
    my ($executable, @args) = @_;
    pipe(my $reader, my $writer) or die "Cannot create command pipe: $!";
    $child = fork();
    die "Cannot launch command: $!" unless defined $child;
    if (!$child) {
        close $reader;
        open STDOUT, '>&', $writer or POSIX::_exit(126);
        open STDERR, '>&', $writer or POSIX::_exit(126);
        close $writer;
        exec {$executable} $executable, @args or POSIX::_exit(127);
    }
    close $writer;
    my $selector = IO::Select->new($reader);
    my $output = '';
    my $deadline = time() + 8;
    while (1) {
        my $remaining = $deadline - time();
        if ($remaining <= 0) {
            stop_child(); close $reader;
            return (0, 'macOS VPN command timed out.');
        }
        next unless $selector->can_read($remaining);
        my $count = sysread($reader, my $buffer, 4096);
        if (!defined $count) { next if $! == EINTR; last }
        last if !$count;
        $output .= $buffer;
        if (length($output) > 65536) {
            stop_child(); close $reader;
            return (0, 'Unexpectedly large response from macOS VPN controls.');
        }
    }
    close $reader;
    # The pipe can close before the process exits. Keep the same time bound.
    while (1) {
        my $pid = waitpid($child, WNOHANG);
        if ($pid == $child) {
            my $ok = $? == 0;
            $child = 0;
            return ($ok, decode('UTF-8', $output, FB_DEFAULT));
        }
        if ($pid < 0 && $! != EINTR) {
            $child = 0;
            return (0, 'Could not collect the macOS VPN command result.');
        }
        if (time() >= $deadline) {
            stop_child(); return (0, 'macOS VPN command timed out.');
        }
        select undef, undef, undef, 0.01;
    }
}

sub wireguard_services {
    my ($text) = @_;
    my @services;
    for my $line (split /\n/, $text) {
        if ($line =~ /^\s*\*?\s*\([^)]+\)\s+([A-Fa-f0-9-]{36})\s+VPN\s+\(com\.wireguard\.macos\)\s+"(.*)"\s+\[VPN:com\.wireguard\.macos\]\s*$/) {
            push @services, { id => $1, name => $2 };
        }
    }
    return \@services;
}

sub snapshot {
    my ($self) = @_;
    my $state = { status => 'unknown', tunnel => $self->{tunnel}, busy => JSON::PP::false };
    my ($ok, $listing) = command($self->{scutil}, '--nc', 'list');
    if (!$ok) { $state->{error} = 'Cannot list macOS VPN services.'; return $state }
    my @matches = grep { lc($_->{id}) eq lc($self->{tunnel}) || $_->{name} eq $self->{tunnel} }
        @{wireguard_services($listing)};
    if (@matches != 1) {
        $state->{error} = @matches
            ? 'More than one WireGuard tunnel matches. Use its service UUID.'
            : 'WireGuard tunnel not found. Check its name or service UUID in shell.toml.';
        return $state;
    }
    $state->{id} = $matches[0]->{id};
    $state->{tunnel} = $matches[0]->{name};
    my ($status_ok, $output) = command($self->{scutil}, '--nc', 'status', $state->{id});
    my ($status) = $output =~ /^\s*(Connected|Disconnected|Connecting|Disconnecting)\s*$/m;
    if (!$status_ok || !defined $status) {
        $state->{error} = 'Cannot read this tunnel’s connection status from macOS.';
        return $state;
    }
    $state->{status} = lc $status;
    return $state;
}

sub publish {
    my ($self, $state) = @_;
    if (my $pending = $self->{pending}) {
        if ($state->{status} eq $pending->{target}) {
            delete $self->{pending};
        } elsif ($state->{error} || time() >= $pending->{deadline}) {
            $self->{error} = $state->{error} || 'The tunnel did not finish changing state. Check the WireGuard app.';
            delete $self->{pending};
        } else {
            $state->{busy} = JSON::PP::true;
            $state->{target} = $pending->{target};
        }
    }
    $state->{error} ||= $self->{error} if $self->{error};
    my $encoded = JSON::PP->new->canonical->encode($state);
    if (!defined($self->{last}) || $encoded ne $self->{last}) {
        emit(['state', 'vpn', $state]);
        $self->{last} = $encoded;
    }
    return $state;
}

sub action {
    my ($self, $name) = @_;
    if ($name eq 'refresh') {
        delete $self->{error};
        return (1, publish($self, snapshot($self)));
    }
    return (0, 'Unknown WireGuard action.') unless $name eq 'toggle';
    return (0, 'The tunnel is already changing state.') if $self->{pending};
    delete $self->{error};
    # Recheck the selected service and its actual state on every click. A stale
    # display or a similarly named VPN must never control another service.
    my $state = snapshot($self);
    if ($state->{error}) { publish($self, $state); return (0, $state->{error}) }
    if ($state->{status} ne 'connected' && $state->{status} ne 'disconnected') {
        publish($self, $state);
        return (0, 'The tunnel is already changing state.');
    }
    my $connect = $state->{status} eq 'disconnected';
    my ($ok, $output) = command($self->{scutil}, '--nc', $connect ? 'start' : 'stop', $state->{id});
    # Successful start/stop is silent; scutil sometimes reports failures in text.
    if (!$ok || $output =~ /\S/) {
        $output =~ s/\s+/ /g;
        $self->{error} = 'macOS could not ' . ($connect ? 'connect' : 'disconnect')
            . ' the tunnel.' . ($output =~ /\S/ ? ' ' . substr($output, 0, 300) : '')
            . ' Check the WireGuard app.';
        publish($self, snapshot($self));
        return (0, $self->{error});
    }
    $self->{pending} = { target => $connect ? 'connected' : 'disconnected', deadline => time() + 25 };
    my $updated = publish($self, snapshot($self));
    return (1, $updated);
}

sub options {
    my $opts = eval { decode_json($ENV{OMNIWM_PROVIDER_OPTIONS} || '{}') };
    die "Invalid WireGuard provider options\n" unless ref($opts) eq 'HASH';
    my $tunnel = $opts->{tunnel} // 'Myworkout Wireguard Client';
    die "Invalid tunnel name or UUID\n" if ref($tunnel) || !length($tunnel) || length($tunnel) > 256;
    my $poll = $opts->{pollSeconds} // 3;
    die "Invalid refresh interval\n" if ref($poll) || $poll !~ /^\d+(?:\.\d+)?$/ || $poll < 1 || $poll > 60;
    return { tunnel => $tunnel, poll => $poll, scutil => '/usr/sbin/scutil' };
}

sub run {
    my (%test) = @_;
    $| = 1;
    $ENV{LC_ALL} = 'C';
    my $self = options();
    # Dependency injection is used by the offline tests, never by the manifest.
    $self->{scutil} = $test{scutil} if $test{scutil};
    publish($self, snapshot($self));
    my $selector = IO::Select->new(\*STDIN);
    my $buffer = '';
    my $next_poll = time() + $self->{poll};
    while (1) {
        my $wait = $next_poll - time();
        $wait = 0 if $wait < 0;
        if ($selector->can_read($wait)) {
            my $count = sysread(STDIN, my $chunk, 4096);
            if (!defined $count) { next if $! == EINTR; last }
            last if !$count;
            $buffer .= $chunk;
            die "Oversized provider action\n" if length($buffer) > 65536 && index($buffer, "\n") < 0;
            while ($buffer =~ s/^(.*?\n)//s) {
                my $line = $1;
                die "Oversized provider action\n" if length($line) > 65536;
                my $frame = eval { decode_json($line) };
                die "Invalid provider action\n" unless ref($frame) eq 'ARRAY' && @$frame == 4
                    && $frame->[0] eq 'action' && defined($frame->[1]) && !ref($frame->[1])
                    && length($frame->[1]) <= 64 && defined($frame->[2]) && !ref($frame->[2]);
                my ($ok, $value) = action($self, $frame->[2]);
                emit(['result', $frame->[1], $ok ? JSON::PP::true : JSON::PP::false, $value]);
            }
            die "Oversized provider action\n" if length($buffer) > 65536;
        }
        if (time() >= $next_poll) {
            publish($self, snapshot($self));
            $next_poll = time() + ($self->{pending} ? 1 : $self->{poll});
        }
    }
}

unless (caller) {
    if (@ARGV && $ARGV[0] eq '--status') {
        my $self = options();
        $self->{tunnel} = $ARGV[1] if defined $ARGV[1];
        $ENV{LC_ALL} = 'C';
        emit(snapshot($self));
    } elsif (@ARGV) {
        die "Usage: provider.pl [--status [tunnel-name-or-service-UUID]]\n";
    } else {
        run();
    }
}
