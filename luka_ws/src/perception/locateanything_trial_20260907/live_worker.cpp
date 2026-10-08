#include "engine.hpp"
#include "image_io.hpp"
#include "visualize.hpp"
#include <chrono>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <string>

using Clock=std::chrono::steady_clock;
static double elapsed(Clock::time_point start) { return std::chrono::duration<double>(Clock::now()-start).count(); }
static std::string escape(const std::string& value) {
    std::string out;
    for (unsigned char c:value) {
        if(c=='"'||c=='\\') {out+='\\';out+=c;}
        else if(c=='\n') out+="\\n";
        else if(c=='\r') out+="\\r";
        else if(c=='\t') out+="\\t";
        else if(c>=32) out+=c;
    }
    return out;
}
int main(int argc,char** argv) {
    if(argc!=2) {std::cerr<<"model image prompt output_prefix [image prompt output_prefix ...]\n";return 2;}
    auto begin=Clock::now();
    auto model=la::Engine::load(argv[1],4);
    if(!model) return 3;
    std::cout<<"{\"event\":\"loaded\",\"seconds\":"<<elapsed(begin)<<"}"<<std::endl;
    std::string input, prompt, prefix;
    while(std::getline(std::cin,input) && std::getline(std::cin,prompt) && std::getline(std::cin,prefix)) {
        begin=Clock::now();
        auto detections=model->locate(input,prompt,la::Engine::Mode::Slow,128);
        auto seconds=elapsed(begin);
        std::ofstream output(std::string(prefix)+".json");
        output<<std::setprecision(8)<<"{\"image\":\""<<escape(input)<<"\",\"prompt\":\""<<escape(prompt)<<"\",\"mode\":\"slow-greedy\",\"inference_seconds\":"<<seconds<<",\"detections\":[";
        for(size_t n=0;n<detections.size();++n) {
            const auto& d=detections[n];
            output<<(n?",":"")<<"{\"label\":\""<<escape(d.label)<<"\",\"box\":["<<d.x1<<","<<d.y1<<","<<d.x2<<","<<d.y2<<"]}";
        }
        output<<"]}";output.close();
        la::Image image;
        if(la::load_image_rgb(input,image)) la::save_image_png(std::string(prefix)+".png",la::render_boxes(image,detections));
        std::cout<<"{\"event\":\"inference\",\"output\":\""<<escape(prefix)<<"\",\"seconds\":"<<seconds<<",\"count\":"<<detections.size()<<"}"<<std::endl;
    }
}
