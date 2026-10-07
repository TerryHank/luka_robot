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
    if(argc<5 || (argc-2)%3) {std::cerr<<"model image prompt output_prefix [image prompt output_prefix ...]\n";return 2;}
    auto begin=Clock::now();
    auto model=la::Engine::load(argv[1],4);
    if(!model) return 3;
    std::cout<<"{\"event\":\"loaded\",\"seconds\":"<<elapsed(begin)<<"}"<<std::endl;
    for(int i=2;i<argc;i+=3) {
        begin=Clock::now();
        auto detections=model->locate(argv[i],argv[i+1],la::Engine::Mode::Slow,128);
        auto seconds=elapsed(begin);
        std::ofstream output(std::string(argv[i+2])+".json");
        output<<std::setprecision(8)<<"{\"image\":\""<<escape(argv[i])<<"\",\"prompt\":\""<<escape(argv[i+1])<<"\",\"mode\":\"slow-greedy\",\"inference_seconds\":"<<seconds<<",\"detections\":[";
        for(size_t n=0;n<detections.size();++n) {
            const auto& d=detections[n];
            output<<(n?",":"")<<"{\"label\":\""<<escape(d.label)<<"\",\"box\":["<<d.x1<<","<<d.y1<<","<<d.x2<<","<<d.y2<<"]}";
        }
        output<<"]}";output.close();
        la::Image image;
        if(la::load_image_rgb(argv[i],image)) la::save_image_png(std::string(argv[i+2])+".png",la::render_boxes(image,detections));
        std::cout<<"{\"event\":\"inference\",\"output\":\""<<escape(argv[i+2])<<"\",\"seconds\":"<<seconds<<",\"count\":"<<detections.size()<<"}"<<std::endl;
    }
}
