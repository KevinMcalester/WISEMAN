#include <iostream>
#include <chrono>
#include <vector>
#include <string>
#include <functional>
#include <thread>
#include <atomic>

using Clock = std::chrono::steady_clock;

struct Task
{
    std::string name;
    std::chrono::milliseconds period;
    Clock::time_point next_run;
    std::function<void()> job;
};

int main()
{
    auto now = Clock::now();
    std::atomic<bool> running{true};

    std::vector<Task> tasks
    {
        {
            "flight_control",
            std::chrono::milliseconds(5),
            now,
            []()
            {
                std::cout << "[CONTROL] Stabilizing / updating control loop\n";
            }
        },

        {
            "command_process",
            std::chrono::milliseconds(5),
            now,
            []()
            {
                std::cout << "[COMMAND] Processing incoming commands\n";
            }
        },

        {
            "camera_capture",
            std::chrono::milliseconds(33), // ~30 FPS
            now,
            []()
            {
                std::cout << "[CAMERA] Capturing latest frame\n";
            }
        },

        {
            "object_detection",
            std::chrono::milliseconds(100), // 10 FPS detection
            now,
            []()
            {
                std::cout << "[VISION] Running object detection on latest frame\n";
            }
        },

        {
            "telemetry_send",
            std::chrono::milliseconds(100),
            now,
            []()
            {
                std::cout << "[TELEMETRY] Sending telemetry update\n";
            }
        },

        {
            "health_monitor",
            std::chrono::milliseconds(250),
            now,
            []()
            {
                std::cout << "[HEALTH] Checking system status\n";
            }
        }
    };

    std::cout << "Timing engine started. Press Ctrl+C to stop.\n\n";

    while (running)
    {
        auto current_time = Clock::now();

        for (auto& task : tasks)
        {
            if (current_time >= task.next_run)
            {
                auto start = Clock::now();

                task.job();

                auto end = Clock::now();
                auto runtime_us =
                    std::chrono::duration_cast<std::chrono::microseconds>(end - start).count();

                std::cout << "  -> " << task.name
                          << " runtime: " << runtime_us << " us\n\n";

                task.next_run += task.period;

                if (current_time > task.next_run)
                {
                    task.next_run = current_time + task.period;
                }
            }
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(1));
    }

    return 0;
}