import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { motion, AnimatePresence } from 'framer-motion';
import { ArrowLeft, Upload, FileText, Ticket, Wallet, Trash2, Eye, X, Plus, FilePlus } from 'lucide-react';
import { API_URL } from '../constants';
import { WALLET } from '../constants/testIds';
import EYVLogo from '../components/EYVLogo';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';

const CATEGORIES = [
  { value: 'boarding_pass', label: 'Boarding Pass', icon: Ticket },
  { value: 'ticket', label: 'Ticket', icon: Ticket },
  { value: 'voucher', label: 'Voucher', icon: FileText },
  { value: 'document', label: 'Document', icon: FileText },
];

const WalletPage = ({ user }) => {
  const navigate = useNavigate();
  const fileInputRef = useRef(null);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showUpload, setShowUpload] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [previewItem, setPreviewItem] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [activeCategory, setActiveCategory] = useState('all');

  const [uploadForm, setUploadForm] = useState({
    file: null,
    title: '',
    category: 'document',
    description: '',
  });

  useEffect(() => {
    fetchItems();
  }, []);

  const fetchItems = async () => {
    try {
      const response = await axios.get(`${API_URL}/wallet`, { withCredentials: true });
      setItems(response.data.items);
    } catch (error) {
      console.error('Error fetching wallet:', error);
    } finally {
      setLoading(false);
    }
  };

  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (file) {
      setUploadForm({ ...uploadForm, file, title: uploadForm.title || file.name });
    }
  };

  const handleUpload = async () => {
    if (!uploadForm.file) {
      alert('Please select a file');
      return;
    }
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', uploadForm.file);
      
      const params = new URLSearchParams({
        category: uploadForm.category,
        title: uploadForm.title,
        description: uploadForm.description,
      });

      await axios.post(
        `${API_URL}/wallet/upload?${params.toString()}`,
        formData,
        {
          withCredentials: true,
          headers: { 'Content-Type': 'multipart/form-data' },
        }
      );

      setShowUpload(false);
      setUploadForm({ file: null, title: '', category: 'document', description: '' });
      fetchItems();
    } catch (error) {
      console.error('Upload error:', error);
      alert('Failed to upload file');
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async (itemId) => {
    if (!window.confirm('Delete this item from your wallet?')) return;
    
    try {
      await axios.delete(`${API_URL}/wallet/${itemId}`, { withCredentials: true });
      fetchItems();
    } catch (error) {
      console.error('Delete error:', error);
    }
  };

  const handlePreview = async (item) => {
    setPreviewItem(item);
    try {
      const response = await axios.get(
        `${API_URL}/wallet/${item.item_id}/download`,
        {
          withCredentials: true,
          responseType: 'blob',
        }
      );
      const url = URL.createObjectURL(response.data);
      setPreviewUrl(url);
    } catch (error) {
      console.error('Preview error:', error);
      alert('Failed to load preview');
    }
  };

  const closePreview = () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null);
    setPreviewItem(null);
  };

  const filteredItems = activeCategory === 'all' 
    ? items 
    : items.filter(item => item.category === activeCategory);

  const getCategoryIcon = (category) => {
    const cat = CATEGORIES.find(c => c.value === category);
    return cat ? cat.icon : FileText;
  };

  return (
    <div data-testid={WALLET.walletContainer} className="min-h-screen bg-[#FDFBF7]">
      <div className="glass sticky top-0 z-50 border-b border-[#E7E5E4]">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Button onClick={() => navigate('/dashboard')} variant="ghost" className="text-[#57534E]">
              <ArrowLeft size={20} />
            </Button>
            <EYVLogo size="small" />
          </div>
          <h2 className="text-2xl font-medium text-[#2A4B5C]" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
            Travel Wallet
          </h2>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-6 py-8">
        <div className="flex items-center justify-between mb-8">
          <div>
            <h1 className="text-4xl font-semibold text-[#1C1917]" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
              Your Travel Documents
            </h1>
            <p className="text-[#57534E] mt-2">Store boarding passes, tickets, and vouchers in one place</p>
          </div>
          <Button
            data-testid={WALLET.uploadButton}
            onClick={() => setShowUpload(true)}
            className="bg-[#C47245] hover:bg-[#A85D38]"
          >
            <Plus size={20} />
            Add Document
          </Button>
        </div>

        {/* Category Filter */}
        <div className="flex gap-2 mb-6 flex-wrap">
          <button
            onClick={() => setActiveCategory('all')}
            className={`px-4 py-2 rounded-full text-sm font-medium transition-all ${
              activeCategory === 'all' ? 'bg-[#C47245] text-white' : 'bg-white text-[#57534E] border border-[#E7E5E4]'
            }`}
          >
            All ({items.length})
          </button>
          {CATEGORIES.map(cat => {
            const count = items.filter(i => i.category === cat.value).length;
            return (
              <button
                key={cat.value}
                onClick={() => setActiveCategory(cat.value)}
                className={`px-4 py-2 rounded-full text-sm font-medium transition-all flex items-center gap-2 ${
                  activeCategory === cat.value ? 'bg-[#C47245] text-white' : 'bg-white text-[#57534E] border border-[#E7E5E4]'
                }`}
              >
                <cat.icon size={14} />
                {cat.label} ({count})
              </button>
            );
          })}
        </div>

        {/* Items Grid */}
        {loading ? (
          <div className="text-center py-12">
            <div className="animate-spin h-12 w-12 border-4 border-[#C47245] border-t-transparent rounded-full mx-auto"></div>
          </div>
        ) : filteredItems.length === 0 ? (
          <div className="text-center py-16 bg-white rounded-2xl border border-[#E7E5E4]">
            <Wallet size={48} className="mx-auto text-[#E7E5E4] mb-4" />
            <p className="text-[#57534E] text-lg mb-4">
              {activeCategory === 'all' ? 'Your wallet is empty' : `No ${activeCategory.replace('_', ' ')}s yet`}
            </p>
            <Button onClick={() => setShowUpload(true)} className="bg-[#C47245] hover:bg-[#A85D38]">
              <FilePlus size={20} />
              Upload Your First Document
            </Button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {filteredItems.map((item) => {
              const Icon = getCategoryIcon(item.category);
              const isImage = item.content_type?.startsWith('image/');
              return (
                <motion.div
                  key={item.item_id}
                  data-testid={WALLET.walletItem}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="bg-white rounded-2xl overflow-hidden border border-[#E7E5E4] hover:shadow-lg transition-all group"
                >
                  <div className="h-40 bg-gradient-to-br from-[#C47245]/10 to-[#E8B273]/20 flex items-center justify-center relative">
                    <Icon size={48} className="text-[#C47245]" />
                    <div className="absolute top-2 right-2 bg-white/90 px-2 py-1 rounded text-xs text-[#57534E] uppercase tracking-wider">
                      {item.category.replace('_', ' ')}
                    </div>
                  </div>
                  <div className="p-4">
                    <h3 className="font-medium text-[#1C1917] truncate mb-1" style={{ fontFamily: 'Cormorant Garamond, serif', fontSize: '1.2rem' }}>
                      {item.title}
                    </h3>
                    {item.description && (
                      <p className="text-sm text-[#57534E] mb-2 line-clamp-2">{item.description}</p>
                    )}
                    <p className="text-xs text-[#86A8B3] mb-3">
                      {new Date(item.created_at).toLocaleDateString()} • {(item.size / 1024).toFixed(1)} KB
                    </p>
                    <div className="flex gap-2">
                      <Button
                        onClick={() => handlePreview(item)}
                        variant="outline"
                        size="sm"
                        className="flex-1"
                      >
                        <Eye size={14} />
                        View
                      </Button>
                      <Button
                        data-testid={WALLET.deleteItem}
                        onClick={() => handleDelete(item.item_id)}
                        variant="outline"
                        size="sm"
                        className="text-red-500 hover:bg-red-50"
                      >
                        <Trash2 size={14} />
                      </Button>
                    </div>
                  </div>
                </motion.div>
              );
            })}
          </div>
        )}
      </div>

      {/* Upload Modal */}
      <AnimatePresence>
        {showUpload && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4"
            onClick={() => setShowUpload(false)}
          >
            <motion.div
              initial={{ scale: 0.95 }}
              animate={{ scale: 1 }}
              className="bg-white rounded-2xl p-8 max-w-md w-full"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-6">
                <h3 className="text-2xl font-medium text-[#1C1917]" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  Add to Wallet
                </h3>
                <button onClick={() => setShowUpload(false)}>
                  <X size={24} className="text-[#57534E]" />
                </button>
              </div>

              <div className="space-y-4">
                <div>
                  <Label className="text-xs uppercase tracking-wider text-[#C47245] font-medium">File (Max 10MB)</Label>
                  <div
                    onClick={() => fileInputRef.current?.click()}
                    className="mt-2 border-2 border-dashed border-[#E7E5E4] rounded-lg p-6 text-center cursor-pointer hover:border-[#C47245] transition-colors"
                  >
                    <Upload size={32} className="mx-auto text-[#C47245] mb-2" />
                    <p className="text-sm text-[#57534E]">
                      {uploadForm.file ? uploadForm.file.name : 'Click to select file (PDF, JPG, PNG)'}
                    </p>
                    <input
                      ref={fileInputRef}
                      data-testid={WALLET.uploadFile}
                      type="file"
                      onChange={handleFileChange}
                      accept=".pdf,.jpg,.jpeg,.png,.gif,.webp"
                      className="hidden"
                    />
                  </div>
                </div>

                <div>
                  <Label className="text-xs uppercase tracking-wider text-[#C47245] font-medium">Title</Label>
                  <Input
                    data-testid={WALLET.uploadTitle}
                    value={uploadForm.title}
                    onChange={(e) => setUploadForm({ ...uploadForm, title: e.target.value })}
                    placeholder="e.g., Maldives Boarding Pass"
                    className="mt-1 border-[#E7E5E4]"
                  />
                </div>

                <div>
                  <Label className="text-xs uppercase tracking-wider text-[#C47245] font-medium">Category</Label>
                  <div className="grid grid-cols-2 gap-2 mt-2">
                    {CATEGORIES.map(cat => (
                      <button
                        key={cat.value}
                        data-testid={`${WALLET.uploadCategory}-${cat.value}`}
                        onClick={() => setUploadForm({ ...uploadForm, category: cat.value })}
                        className={`p-3 rounded-lg border-2 transition-all flex items-center gap-2 ${
                          uploadForm.category === cat.value ? 'border-[#C47245] bg-[#C47245]/10' : 'border-[#E7E5E4]'
                        }`}
                      >
                        <cat.icon size={18} className="text-[#C47245]" />
                        <span className="text-sm text-[#1C1917]">{cat.label}</span>
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <Label className="text-xs uppercase tracking-wider text-[#C47245] font-medium">Description (Optional)</Label>
                  <Input
                    value={uploadForm.description}
                    onChange={(e) => setUploadForm({ ...uploadForm, description: e.target.value })}
                    placeholder="Add notes..."
                    className="mt-1 border-[#E7E5E4]"
                  />
                </div>
              </div>

              <div className="flex gap-3 mt-6">
                <Button onClick={() => setShowUpload(false)} variant="outline" className="flex-1">
                  Cancel
                </Button>
                <Button
                  data-testid={WALLET.uploadSubmit}
                  onClick={handleUpload}
                  disabled={uploading || !uploadForm.file}
                  className="flex-1 bg-[#C47245] hover:bg-[#A85D38]"
                >
                  {uploading ? 'Uploading...' : 'Upload'}
                </Button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Preview Modal */}
      <AnimatePresence>
        {previewItem && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4"
            onClick={closePreview}
          >
            <motion.div
              initial={{ scale: 0.95 }}
              animate={{ scale: 1 }}
              className="bg-white rounded-2xl p-6 max-w-4xl max-h-[90vh] overflow-auto w-full"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-xl font-medium text-[#1C1917]" style={{ fontFamily: 'Cormorant Garamond, serif' }}>
                  {previewItem.title}
                </h3>
                <button onClick={closePreview}>
                  <X size={24} className="text-[#57534E]" />
                </button>
              </div>
              {previewUrl ? (
                previewItem.content_type?.startsWith('image/') ? (
                  <img src={previewUrl} alt={previewItem.title} className="w-full h-auto rounded-lg" />
                ) : previewItem.content_type === 'application/pdf' ? (
                  <iframe src={previewUrl} title="PDF Preview" className="w-full h-[70vh] rounded-lg" />
                ) : (
                  <div className="text-center py-12">
                    <a href={previewUrl} download={previewItem.original_filename} className="text-[#C47245] underline">
                      Download {previewItem.original_filename}
                    </a>
                  </div>
                )
              ) : (
                <div className="text-center py-12">
                  <div className="animate-spin h-12 w-12 border-4 border-[#C47245] border-t-transparent rounded-full mx-auto"></div>
                </div>
              )}
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
};

export default WalletPage;
